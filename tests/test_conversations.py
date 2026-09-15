import asyncio
import json
from functools import partial

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from strands.storage import InMemoryStorage, S3Storage

from agent import create_dietitian_agent, DIETITIAN_SYSTEM_PROMPT
from imhungry.api import create_app
from imhungry.conversations import ConversationService
from imhungry.demo import DemoModel
from imhungry.errors import AppError, Conflict, NotFound
from imhungry.providers import run_async
from imhungry.repository import Write
from test_services import service, PROFILE
from test_repository import repo


@pytest.fixture
def conversations(service):
    return ConversationService(service, InMemoryStorage(), partial(create_dietitian_agent, model=DemoModel()))


def test_real_strands_loop_logs_restores_and_selects_context(conversations):
    async def flow():
        services = conversations.services
        services.update("alice", "profile", "profile", PROFILE, 0)
        metadata = conversations.create("alice", {"title": "Food choices"}, "create")
        cid = metadata["conversation_id"]
        hello = await conversations.invoke("alice", cid, "Hello", "hello")
        assert "Hello" in hello["response"]
        first = await conversations.invoke("alice", cid, "Log demo yogurt", "log")
        assert "Saved" in first["response"]
        assert await conversations.invoke("alice", cid, "Log demo yogurt", "log") == first
        assert len(services.records("alice", "food-log", "2026-09-14")) == 1
        # A fresh ConversationService and Agent restore the same native snapshot.
        restored = ConversationService(services, conversations.storage, partial(create_dietitian_agent, model=DemoModel()))
        dinner = await restored.invoke("alice", cid, "What should I eat for dinner?", "dinner")
        assert "150 kcal" in dinner["response"]
        messages = await restored.messages("alice", cid)
        assert [m["role"] for m in messages["messages"]] == ["user", "assistant"] * 3
        assert "toolUse" not in json.dumps(messages)
        assert messages["messages"][3]["tool_activity"] == [{"name": "log_food", "status": "completed"}]
        assert messages["messages"][5]["tool_activity"] == [{"name": "get_meal_decision_context", "status": "completed"}]
        keys = await conversations.storage.list("")
        assert keys == [f"session/{cid}/scopes/agent/dietitian/snapshots/snapshot_latest.json"]
        snapshot = json.loads(await conversations.storage.read(keys[0]))
        assert snapshot["schema_version"] == "1.0"
        assert snapshot["scope"] == "agent"
        assert set(snapshot["data"]) >= {"messages", "state", "conversation_manager_state", "system_prompt"}
        uses = [block["toolUse"] for m in snapshot["data"]["messages"] for block in m["content"] if "toolUse" in block]
        assert [u["name"] for u in uses] == ["log_food", "get_meal_decision_context"]
        assert "services" not in snapshot["data"]["state"]
        with pytest.raises(NotFound):
            await restored.invoke("bob", cid, "Read their meals", "stolen")
        with pytest.raises(NotFound):
            await restored.messages("bob", cid)
        with pytest.raises(Conflict):
            await restored.invoke("alice", cid, "Different payload", "log")
    run_async(flow)


def test_conversation_http_and_delete(conversations):
    client = TestClient(create_app(conversations.services, verifier=lambda token: token, conversations=conversations))
    headers = {"Authorization": "Bearer alice", "Idempotency-Key": "create"}
    created = client.post("/v1/conversations", json={"title": "Dinner"}, headers=headers)
    assert created.status_code == 201, created.text
    cid = created.json()["conversation_id"]
    path = "/v1/conversations/" + cid
    response = client.post(path + "/messages", json={"message": "Hello", "client_request_id": "hello"}, headers={"Authorization": "Bearer alice"})
    assert response.status_code == 200, response.text
    assert client.get(path + "/messages", headers=headers).json()["messages"][0]["text"] == "Hello"
    assert client.post(path + "/messages", json={"message": "Hello"}, headers={"Authorization": "Bearer alice"}).status_code == 422
    assert len(client.get("/v1/conversations", headers=headers).json()["items"]) == 1
    version = response.json()["version"]
    archive = client.patch(path, json={"status": "archived"}, headers={**headers, "If-Match": str(version)})
    assert archive.status_code == 200
    assert client.post(path + "/messages", json={"message": "No"}, headers={**headers, "Idempotency-Key": "other"}).status_code == 409
    assert client.delete(path, headers={**headers, "If-Match": str(archive.json()["version"])}).status_code == 200
    assert run_async(lambda: conversations.storage.list("")) == []
    assert client.get(path, headers=headers).status_code == 404
    receipts = conversations.repo.query("alice", "REQUEST#", "REQUEST#~")
    assert not [r for r in receipts if r.get("result", {}).get("conversation_id") == cid]


def test_overlapping_invocation_and_patch_are_rejected(conversations):
    async def flow():
        entered, release = asyncio.Event(), asyncio.Event()
        class WaitingModel(DemoModel):
            async def stream(self, *args, **kwargs):
                entered.set()
                await release.wait()
                async for event in super().stream(*args, **kwargs):
                    yield event
        conversations.agent_factory = partial(create_dietitian_agent, model=WaitingModel())
        metadata = conversations.create("alice", {}, "create")
        cid = metadata["conversation_id"]
        running = asyncio.create_task(conversations.invoke("alice", cid, "Hello", "one"))
        await asyncio.wait_for(entered.wait(), 5)
        with pytest.raises(Conflict):
            await conversations.invoke("alice", cid, "Another turn", "two")
        with pytest.raises(Conflict):
            conversations.update("alice", cid, {"title": "Rename"}, metadata["version"])
        with pytest.raises(Conflict):
            await conversations.delete("alice", cid, metadata["version"])
        release.set()
        assert "Hello" in (await running)["response"]
    run_async(flow)


def test_snapshot_failure_blocks_replay_after_tool_write(conversations):
    class BrokenStorage(InMemoryStorage):
        async def write(self, key, data):
            raise RuntimeError("private storage diagnostic")
    conversations.storage = BrokenStorage()
    cid = conversations.create("alice", {}, "create")["conversation_id"]
    with pytest.raises(AppError, match="blocked pending recovery"):
        run_async(lambda: conversations.invoke("alice", cid, "Log demo yogurt", "log"))
    assert conversations.get("alice", cid)["invocation_state"] == "failed"
    assert len(conversations.services.records("alice", "food-log", "2026-09-14")) == 1
    with pytest.raises(Conflict):
        run_async(lambda: conversations.invoke("alice", cid, "Log demo yogurt", "new-request"))
    assert run_async(lambda: conversations.storage.list("")) == []


def test_missing_snapshot_fails_closed(conversations):
    cid = conversations.create("alice", {}, "create")["conversation_id"]
    run_async(lambda: conversations.invoke("alice", cid, "Hello", "first"))
    key = run_async(lambda: conversations.storage.list(""))[0]
    run_async(lambda: conversations.storage.delete(key))
    with pytest.raises(AppError):
        run_async(lambda: conversations.invoke("alice", cid, "Hello again", "second"))
    assert conversations.get("alice", cid)["invocation_state"] == "failed"


def test_native_s3_layout_and_restore(conversations):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="imhungry-test-snapshots")
        conversations.storage = S3Storage("imhungry-test-snapshots", prefix="imhungry/test", region_name="us-east-1")
        cid = conversations.create("alice", {}, "create")["conversation_id"]
        run_async(lambda: conversations.invoke("alice", cid, "Hello", "first"))
        keys = [x["Key"] for x in s3.list_objects_v2(Bucket="imhungry-test-snapshots")["Contents"]]
        assert keys == [f"imhungry/test/session/{cid}/scopes/agent/dietitian/snapshots/snapshot_latest.json"]
        assert len(run_async(lambda: conversations.messages("alice", cid))["messages"]) == 2
        version = conversations.get("alice", cid)["version"]
        run_async(lambda: conversations.delete("alice", cid, version))
        assert s3.list_objects_v2(Bucket="imhungry-test-snapshots")["KeyCount"] == 0


def test_coaching_prompt_preserves_scope():
    assert "compensatory" in DIETITIAN_SYSTEM_PROMPT
    assert "explicit confirmation" in DIETITIAN_SYSTEM_PROMPT
    assert "never workout programming" in DIETITIAN_SYSTEM_PROMPT


def test_tool_retry_keys_are_scoped_to_conversation(conversations):
    for key in ("one", "two"):
        cid = conversations.create("alice", {}, key)["conversation_id"]
        run_async(lambda: conversations.invoke("alice", cid, "Log demo yogurt", "same-client-key"))
    assert len(conversations.services.records("alice", "food-log", "2026-09-14")) == 2


def test_metadata_commit_failure_after_snapshot_stays_blocked(conversations, monkeypatch):
    cid = conversations.create("alice", {}, "create")["conversation_id"]
    def unavailable(*args, **kwargs):
        raise RuntimeError("backend diagnostic")
    monkeypatch.setattr(conversations.services, "_commit", unavailable)
    with pytest.raises(AppError, match="blocked pending recovery"):
        run_async(lambda: conversations.invoke("alice", cid, "Hello", "hello"))
    assert run_async(lambda: conversations.storage.list(""))
    assert conversations.get("alice", cid)["invocation_state"] == "failed"


def test_http_upstream_errors_are_sanitized(conversations):
    class BrokenStorage(InMemoryStorage):
        async def read(self, key):
            raise RuntimeError("private-storage-identifier")
    conversations.storage = BrokenStorage()
    cid = conversations.create("alice", {}, "create")["conversation_id"]
    client = TestClient(create_app(conversations.services, verifier=lambda token: token, conversations=conversations))
    response = client.post(f"/v1/conversations/{cid}/messages", json={"message": "Hello"},
                           headers={"Authorization": "Bearer alice", "Idempotency-Key": "hello"})
    assert response.status_code == 503
    assert "private-storage-identifier" not in response.text
    assert "request_id" in response.json()
