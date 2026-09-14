"""Atomic, user-scoped repository ports with memory and DynamoDB adapters."""

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from threading import RLock
from typing import Protocol

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from .errors import AppError, Conflict


@dataclass(frozen=True)
class Write:
    key: str
    item: dict | None
    expected_version: int = 0  # zero means absent; None item means delete


class Repository(Protocol):
    def get(self, user: str, key: str) -> dict | None: ...

    def query(self, user: str, lower: str, upper: str, *, reverse: bool = False,
              limit: int | None = None, index: bool = False) -> list[dict]: ...

    def transact(self, user: str, writes: list[Write]) -> None: ...


def partition(user):
    if not isinstance(user, str) or not user or len(user) > 128 or "#" in user:
        raise AppError("identity", "Invalid authenticated identity", 401)
    return f"USER#{user}"


class MemoryRepository:
    """Local fake, not a production persistence option. Atomic across threads."""

    def __init__(self):
        self.items = {}
        self.lock = RLock()

    def get(self, user, key):
        with self.lock:
            return deepcopy(self.items.get((partition(user), key)))

    def query(self, user, lower, upper, *, reverse=False, limit=None, index=False):
        with self.lock:
            field = "GSI1SK" if index else "SK"
            items = [deepcopy(item) for (pk, _), item in self.items.items()
                     if pk == partition(user) and field in item and lower <= item[field] <= upper]
            return sorted(items, key=lambda item: item[field], reverse=reverse)[:limit]

    def transact(self, user, writes):
        pk = partition(user)
        if len({w.key for w in writes}) != len(writes):
            raise ValueError("A transaction cannot target the same key twice")
        with self.lock:
            for write in writes:
                old = self.items.get((pk, write.key))
                if (write.expected_version == 0 and old is not None) or (
                    write.expected_version != 0 and (old is None or old.get("version") != write.expected_version)
                ):
                    raise Conflict()
            for write in writes:
                if write.item is None:
                    self.items.pop((pk, write.key), None)
                else:
                    self.items[pk, write.key] = deepcopy({**write.item, "PK": pk, "SK": write.key})


def decimalize(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: decimalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decimalize(v) for v in value]
    return value


def native(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: native(v) for k, v in value.items()}
    if isinstance(value, list):
        return [native(v) for v in value]
    return value


class DynamoRepository:
    """Uses an injected low-level boto3 client, reusable safely across threads.

    Explicit serialization is needed for transactional conditional moves. No
    client construction, credentials, scans, or resource provisioning occurs here.
    """

    def __init__(self, client, table_name):
        self.client, self.table = client, table_name
        self.serializer, self.deserializer = TypeSerializer(), TypeDeserializer()

    def encode(self, item):
        return {k: self.serializer.serialize(decimalize(v)) for k, v in item.items()}

    def decode(self, item):
        return native({k: self.deserializer.deserialize(v) for k, v in item.items()})

    def get(self, user, key):
        item = self.client.get_item(TableName=self.table, ConsistentRead=True,
                                    Key=self.encode({"PK": partition(user), "SK": key})).get("Item")
        return self.decode(item) if item else None

    def query(self, user, lower, upper, *, reverse=False, limit=None, index=False):
        pk, sk = ("GSI1PK", "GSI1SK") if index else ("PK", "SK")
        args = dict(TableName=self.table, KeyConditionExpression="#pk = :pk AND #sk BETWEEN :lo AND :hi",
                    ExpressionAttributeNames={"#pk": pk, "#sk": sk},
                    ExpressionAttributeValues=self.encode({":pk": partition(user), ":lo": lower, ":hi": upper}),
                    ScanIndexForward=not reverse, ConsistentRead=not index)
        if index:
            args["IndexName"] = "GSI1"
        if limit:
            args["Limit"] = limit
        results = []
        for page in self.client.get_paginator("query").paginate(**args):
            results.extend(self.decode(item) for item in page.get("Items", []))
            if limit and len(results) >= limit:
                return results[:limit]
        return results

    def transact(self, user, writes):
        pk = partition(user)
        operations = []
        for write in writes:
            args = {"TableName": self.table}
            if write.expected_version == 0:
                args.update(ConditionExpression="attribute_not_exists(#pk)", ExpressionAttributeNames={"#pk": "PK"})
            else:
                args.update(ConditionExpression="#v = :v", ExpressionAttributeNames={"#v": "version"},
                            ExpressionAttributeValues=self.encode({":v": write.expected_version}))
            if write.item is None:
                args["Key"] = self.encode({"PK": pk, "SK": write.key})
                operations.append({"Delete": args})
            else:
                args["Item"] = self.encode({**write.item, "PK": pk, "SK": write.key})
                operations.append({"Put": args})
        try:
            self.client.transact_write_items(TransactItems=operations)
        except self.client.exceptions.TransactionCanceledException as error:
            reasons = error.response.get("CancellationReasons", [])
            if any(r.get("Code") in {"ConditionalCheckFailed", "TransactionConflict"} for r in reasons):
                raise Conflict() from None
            raise
