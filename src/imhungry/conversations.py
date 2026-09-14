"""Own conversations and coordinate native snapshots with durable product data."""

from copy import deepcopy
from uuid import uuid4

from strands.session import SnapshotSessionManager

from .errors import AppError, Conflict, NotFound
from .repository import Write, partition
from .services import digest


class ConversationService:
    def __init__(self, services, storage, agent_factory):
        self.services, self.repo = services, services.repo
        self.storage, self.agent_factory = storage, agent_factory

    def _owned(self, user, conversation_id):
        key = self.services.key("conversations", conversation_id)
        item = self.repo.get(user, key)
        if item is None:
            raise NotFound()
        return key, item

    def _lock(self, user, key, item, request_id, *, expected_version=None):
        if item.get("invocation_id"):
            raise Conflict("Conversation has an active or unreconciled invocation")
        if expected_version is not None and item["version"] != expected_version:
            raise Conflict()
        locked = {**item, "version": item["version"] + 1, "invocation_id": request_id, "invocation_status": "running"}
        self.repo.transact(user, [Write(key, locked, item["version"])])
        return locked

    def _failed(self, user, key, invocation_id):
        # Never unlock ambiguous failures: tool writes or S3 may have committed.
        item = self.repo.get(user, key)
        if item and item.get("invocation_id") == invocation_id:
            failed = {**item, "version": item["version"] + 1, "invocation_status": "failed"}
            self.repo.transact(user, [Write(key, failed, item["version"])])

    def _manager(self, conversation_id):
        # Save explicitly after successful completion. No automatic failed-turn
        # snapshots, no immutable history, and no changes to native serialization.
        return SnapshotSessionManager(conversation_id, storage=self.storage, save_latest_on="trigger")

    async def _open(self, item):
        conversation_id = item["conversation_id"]
        if item.get("has_snapshot"):
            key = f"session/{conversation_id}/scopes/agent/dietitian/snapshots/snapshot_latest.json"
            if await self.storage.read(key) is None:
                raise AppError("snapshot_missing", "Conversation snapshot is missing; recovery is required", 503)
        manager = self._manager(conversation_id)
        agent = self.agent_factory(session_manager=manager)
        return manager, agent

    def create(self, user, request, request_id):
        return self.services.create(user, "conversations", request, request_id)

    def get(self, user, conversation_id):
        _, item = self._owned(user, conversation_id)
        result = self.services.public(item)
        result["invocation_state"] = item.get("invocation_status", "idle")
        return result

    def update(self, user, conversation_id, patch, expected_version):
        key, item = self._owned(user, conversation_id)
        if item.get("invocation_id"):
            raise Conflict("Conversation has an active or unreconciled invocation")
        # Both this update and lock acquisition condition on the same version.
        # Preserve snapshot markers while validating user-editable metadata.
        if item["version"] != expected_version:
            raise Conflict()
        from .models import Conversation
        data = Conversation.model_validate({**self.services._domain("conversations", item), **patch}).data()
        now = self.services.now()
        updated = {**item, **data, "version": item["version"] + 1, "updated_at": now,
                   "GSI1SK": now + "#" + conversation_id}
        self.repo.transact(user, [Write(key, updated, expected_version)])
        return self.services.public(updated)

    async def messages(self, user, conversation_id):
        _, item = self._owned(user, conversation_id)
        _, agent = await self._open(item)
        messages = []
        for message in agent.messages:
            if message["role"] not in {"user", "assistant"}:
                continue
            text = "\n".join(block["text"] for block in message["content"] if isinstance(block.get("text"), str))
            if text:
                messages.append({"role": message["role"], "text": text})
        return {"messages": messages, "note": "Restorable conversation view; older messages may be summarized by Strands."}

    async def invoke(self, user, conversation_id, message, request_id):
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 12000:
            raise AppError("validation", "Message must contain 1 to 12000 characters")
        key, item = self._owned(user, conversation_id)
        receipt, fingerprint, previous = self.services._receipt(user, f"message:{conversation_id}", request_id, message)
        if previous is not None:
            return previous
        if item["status"] != "active":
            raise Conflict("Unarchive the conversation before sending a message")
        invocation_id = str(uuid4())
        locked = self._lock(user, key, item, invocation_id)
        try:
            manager, agent = await self._open(locked)
            from agent import DIETITIAN_SYSTEM_PROMPT
            agent.system_prompt = DIETITIAN_SYSTEM_PROMPT + f"\nTrusted current local date: {self.services.today(user)}."
            result = await agent.invoke_async(message,
                invocation_state={"user_id": user, "conversation_id": conversation_id, "services": self.services,
                                  "request_id": digest([user, conversation_id, request_id]),
                                  "local_date": str(self.services.today(user))},
                idempotency_token=request_id)
            response = str(result).strip()
            if not response:
                raise AppError("empty_response", "Agent returned no response", 503)
            await manager.save_snapshot(agent, is_latest=True)
            now = self.services.now()
            completed = {k: deepcopy(v) for k, v in locked.items() if k not in {"invocation_id", "invocation_status"}}
            completed.update(version=locked["version"] + 1, updated_at=now, has_snapshot=True,
                             GSI1PK=partition(user), GSI1SK=now + "#" + conversation_id)
            output = {"conversation_id": conversation_id, "response": response, "version": completed["version"]}
            return self.services._commit(user, [Write(key, completed, locked["version"])], receipt, fingerprint, output)
        except Exception:
            self._failed(user, key, invocation_id)
            raise AppError("conversation_failed", "Turn could not be completed; it is blocked pending recovery and must not be retried as a new request", 503) from None

    async def delete(self, user, conversation_id, expected_version):
        key, item = self._owned(user, conversation_id)
        invocation_id = str(uuid4())
        locked = self._lock(user, key, item, invocation_id, expected_version=expected_version)
        try:
            await self._manager(conversation_id).delete_session()
            receipts = self.repo.query(user, "REQUEST#", "REQUEST#~")
            related = [r for r in receipts if r.get("result", {}).get("conversation_id") == conversation_id]
            for offset in range(0, len(related), 90):
                self.repo.transact(user, [Write(r["SK"], None, r["version"]) for r in related[offset:offset + 90]])
            self.repo.transact(user, [Write(key, None, locked["version"])])
            return {"deleted": True, "conversation_id": conversation_id}
        except Exception:
            self._failed(user, key, invocation_id)
            raise AppError("conversation_failed", "Deletion requires recovery; conversation remains blocked", 503) from None
