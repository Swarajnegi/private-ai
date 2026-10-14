"""LAYER: Brain transport — request-bound, single-use owner approval.

THE BIG PICTURE: a model's tool proposal is not permission to execute it.
THE FLOW: bind exact arguments -> publish -> wait -> authenticate decision -> consume.
"""
from __future__ import annotations
import asyncio
from copy import deepcopy
import hashlib
import json
import time
from typing import Callable
import uuid

from jarvis_core.agent.permissions import PermissionDecision


class ApprovalBroker:
    def __init__(self, clock: Callable[[], float] = time.time, ttl: float = 600) -> None:
        self.clock, self.ttl = clock, ttl
        self.requests: dict[str, dict] = {}
        self.records: dict[str, dict] = {}

    def register(self, request_id: str, session: str, cancel: Callable, attached: bool = True) -> None:
        if request_id not in self.requests:
            self.requests[request_id] = {"session": session, "cancel": cancel, "attached": attached, "state": "running", "completed_actions": []}

    def attach(self, request_id: str, session: str, attached: bool = True) -> None:
        request = self.requests.get(request_id)
        if request is None or request["session"] != session:
            raise ValueError("Request/session mismatch")
        request["attached"] = attached

    def pending_for(self, session: str) -> list[dict]:
        return [self.public(r) for r in self.records.values() if r["session"] == session and r["status"] == "pending" and r["expires_at"] > self.clock()]

    def has_pending(self, request_id: str) -> bool:
        return any(r["request_id"] == request_id and r["status"] == "pending" and r["expires_at"] > self.clock() for r in self.records.values())

    @staticmethod
    def public(record: dict) -> dict:
        return deepcopy({k: v for k, v in record.items() if k != "future"})

    async def wait(self, request_id: str, tool: str, arguments: dict, emit: Callable) -> PermissionDecision:
        request = self.requests[request_id]
        proposal = deepcopy(arguments)
        if tool in {"file_create", "file_edit"}:
            from jarvis_core.agent.tools.file_write import FileCreateTool, FileEditTool
            writer = FileCreateTool() if tool == "file_create" else FileEditTool()
            try:
                diff = await asyncio.to_thread(writer.proposal, proposal)
                proposal["proposed_diff"] = diff["diff"]
            except (OSError, ValueError, UnicodeError) as exc:
                await emit("approval_unavailable", {"request_id": request_id, "session": request["session"], "reason": str(exc)})
                return PermissionDecision.DENY
        identity = {"request_id": request_id, "session": request["session"], "tool": tool, "arguments": deepcopy(arguments)}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        record = {**identity, "id": uuid.uuid4().hex, "digest": digest, "proposal": proposal,
                  "reason": "This action needs your approval", "expires_at": self.clock() + self.ttl,
                  "status": "pending", "future": asyncio.get_running_loop().create_future()}
        self.records[record["id"]] = record
        request["state"] = "awaiting_approval"
        await emit("approval", self.public(record))
        try:
            decision = await asyncio.wait_for(record["future"], self.ttl)
            return PermissionDecision.ALLOW if decision == "approve" else PermissionDecision.DENY
        except asyncio.TimeoutError:
            record["status"] = "expired"
            await emit("approval_expired", self.public(record))
            raise asyncio.CancelledError("Approval expired; request terminated")
        finally:
            if request["state"] != "stopping":
                request["state"] = "running"
            if record["status"] == "pending":
                record["status"] = "cancelled"
            await emit("approval_resolved", self.public(record))

    def decide(self, approval_id: str, *, request_id: str, session: str, digest: str, decision: str) -> dict:
        record = self.records.get(approval_id)
        if record is None:
            raise ValueError("Approval no longer exists")
        if record["request_id"] != request_id or record["session"] != session or record["digest"] != digest:
            raise ValueError("Approval does not match this exact request/action")
        if record["status"] != "pending" or record["expires_at"] <= self.clock():
            raise ValueError("Approval already resolved or expired")
        if decision not in {"approve", "deny"}:
            raise ValueError("Decision must be approve or deny")
        if not self.requests.get(request_id, {}).get("attached"):
            raise ValueError("Reconnect to this request before deciding")
        record["status"] = "approved" if decision == "approve" else "denied"
        record["future"].set_result(decision)
        return self.public(record)

    def invalidate(self, request_id: str) -> None:
        request = self.requests.get(request_id)
        if request:
            request["state"] = "stopping"
        for record in self.records.values():
            if record["request_id"] == request_id and record["status"] == "pending":
                record["status"] = "cancelled"
                record["future"].cancel()

    def finish(self, request_id: str) -> None:
        self.invalidate(request_id)
        self.requests.pop(request_id, None)
        self.records = {k: r for k, r in self.records.items() if r["request_id"] != request_id}

    async def cancel(self, request_id: str, session: str) -> None:
        request = self.requests.get(request_id)
        if request is None or request["session"] != session:
            raise ValueError("Request/session mismatch or already finished")
        self.invalidate(request_id)
        await request["cancel"]()


if __name__ == "__main__":
    print("ApprovalBroker retains pending approvals in memory for 600 seconds")
