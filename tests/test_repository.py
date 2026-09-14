from concurrent.futures import ThreadPoolExecutor

import boto3
import pytest
from botocore.stub import Stubber
from moto import mock_aws

from imhungry.errors import Conflict
from imhungry.repository import DynamoRepository, MemoryRepository, Write


@pytest.fixture(params=["memory", "dynamo"])
def repo(request):
    if request.param == "memory":
        yield MemoryRepository()
        return
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(TableName="nutrition", BillingMode="PAY_PER_REQUEST",
                            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
                            AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k in ["PK", "SK", "GSI1PK", "GSI1SK"]],
                            GlobalSecondaryIndexes=[{"IndexName": "GSI1", "KeySchema": [{"AttributeName": "GSI1PK", "KeyType": "HASH"}, {"AttributeName": "GSI1SK", "KeyType": "RANGE"}], "Projection": {"ProjectionType": "ALL"}}])
        yield DynamoRepository(client, "nutrition")


def test_atomic_move_version_and_isolation(repo):
    repo.transact("alice", [Write("INTAKE#a", {"version": 1, "energy": 123.45})])
    assert repo.get("bob", "INTAKE#a") is None
    assert repo.query("bob", "INTAKE#", "INTAKE#~") == []
    with pytest.raises(Conflict):
        repo.transact("alice", [Write("INTAKE#a", None, 2), Write("INTAKE#b", {"version": 2})])
    assert repo.get("alice", "INTAKE#b") is None
    repo.transact("alice", [Write("INTAKE#a", None, 1), Write("INTAKE#b", {"version": 2, "energy": 123.45})])
    assert repo.get("alice", "INTAKE#a") is None
    assert repo.get("alice", "INTAKE#b")["energy"] == 123.45
    with pytest.raises(Conflict):
        repo.transact("alice", [Write("INTAKE#b", {"version": 1})])


def test_bounds_reverse_limit_sparse_index(repo):
    for n in range(4):
        repo.transact("alice", [Write(f"INTAKE#{n}", {"version": 1})])
    assert [x["SK"] for x in repo.query("alice", "INTAKE#1", "INTAKE#3", reverse=True, limit=2)] == ["INTAKE#3", "INTAKE#2"]
    assert repo.query("alice", "!", "~", index=True) == []
    repo.transact("alice", [Write("CONVERSATION#c", {"version": 1, "GSI1PK": "USER#alice", "GSI1SK": "2026#c"})])
    assert len(repo.query("alice", "!", "~", index=True)) == 1


def test_all_dynamodb_pages_consumed():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        repo = DynamoRepository(client, "nutrition")
        with Stubber(client) as stub:
            stub.add_response("query", {"Items": [repo.encode({"SK": "a"})], "LastEvaluatedKey": repo.encode({"PK": "USER#alice", "SK": "a"})})
            stub.add_response("query", {"Items": [repo.encode({"SK": "b"})]})
            assert [x["SK"] for x in repo.query("alice", "a", "z")] == ["a", "b"]
            stub.assert_no_pending_responses()


def test_concurrent_versions_have_one_winner():
    repo = MemoryRepository()
    repo.transact("alice", [Write("PROFILE", {"version": 1})])
    def update(_):
        try:
            repo.transact("alice", [Write("PROFILE", {"version": 2}, 1)])
            return True
        except Conflict:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(update, range(8))) == 1
