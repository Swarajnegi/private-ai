"""LAYER: Brain transport — an approval wait belongs to the request, not its socket.

THE BIG PICTURE: disconnected approval waits can reconnect without re-execution.
THE FLOW: own the slot -> stream events -> detach or cancel -> confirmed cleanup.
"""
from __future__ import annotations
import asyncio
import uuid
from typing import Any, Awaitable, Callable, Dict


async def start_request(hearth: Any, question: str, kwargs: Dict[str, Any], scope: Dict[str, Any], receive: Callable[[], Awaitable[dict]], send: Callable[[dict], Awaitable[None]]) -> None:
    request_id = uuid.uuid4().hex
    session = kwargs.get("session") or "terminal-" + request_id
    kwargs["session"] = session
    await hearth._slot.acquire()
    exchange = {"request_id": request_id, "session": session, "listeners": set(), "events": [], "payload": None}
    hearth._http_requests[request_id] = exchange
    hearth.requests_served += 1

    async def emit(event: str, data: Dict[str, Any]) -> None:
        item = (event, {"request_id": request_id, "session": session, **data})
        exchange["events"].append(item)
        for listener in tuple(exchange["listeners"]):
            listener.put_nowait(item)

    async def perform() -> None:
        try:
            await emit("open", {"question": question})
            payload = await hearth.run_ask(question, emit, **kwargs, request_id=request_id)
            exchange["payload"] = payload
            await emit("answer", payload)
        except asyncio.CancelledError:
            completed = hearth.approvals.requests.get(request_id, {}).get("completed_actions", [])
            exchange["payload"] = {"ok": False, "answer": "", "status": "terminated", "request_id": request_id, "completed_actions": completed}
            await emit("terminated", exchange["payload"])
        finally:
            hearth.approvals.finish(request_id)
            hearth._slot.release()
            if not exchange["listeners"]:
                hearth._http_requests.pop(request_id, None)

    async def cancel_http() -> None:
        exchange["task"].cancel()
        await exchange["task"]

    hearth.approvals.register(request_id, session, cancel_http)
    exchange["task"] = asyncio.create_task(perform())
    await serve_exchange(hearth, exchange, scope, receive, send)


async def serve_exchange(hearth: Any, exchange: Dict[str, Any], scope: Dict[str, Any], receive: Callable[[], Awaitable[dict]], send: Callable[[dict], Awaitable[None]]) -> None:
    from jarvis_core.serve.hearth import _wants_stream, _json_bytes, _respond, _sse
    request_id, session = exchange["request_id"], exchange["session"]
    queue = asyncio.Queue()
    for item in exchange["events"]:
        queue.put_nowait(item)
    exchange["listeners"].add(queue)
    if request_id in hearth.approvals.requests:
        hearth.approvals.attach(request_id, session)
    streaming = _wants_stream(scope)
    disconnected = asyncio.Event()

    async def watch() -> None:
        while not exchange["task"].done():
            msg = await receive()
            if msg["type"] == "http.disconnect":
                disconnected.set()
                return
            await asyncio.sleep(.01)
    watcher = asyncio.create_task(watch())
    logs = []
    try:
        if streaming:
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/event-stream"), (b"cache-control", b"no-store")]})
        while not disconnected.is_set():
            try:
                event, data = await asyncio.wait_for(queue.get(), .1)
            except asyncio.TimeoutError:
                if exchange["task"].done() and queue.empty():
                    break
                continue
            if event == "log":
                logs.append(data.get("line", ""))
            if streaming:
                await send({"type": "http.response.body", "body": _sse(event, data), "more_body": True})
        if not disconnected.is_set():
            if streaming:
                await send({"type": "http.response.body", "body": b"", "more_body": False})
            else:
                payload = {**(exchange["payload"] or {}), "log": logs}
                await _respond(send, 200 if payload.get("ok") else 500, _json_bytes(payload))
    finally:
        watcher.cancel()
        exchange["listeners"].discard(queue)
        if request_id in hearth.approvals.requests:
            hearth.approvals.attach(request_id, session, bool(exchange["listeners"]))
        if not exchange["listeners"] and not exchange["task"].done() and not hearth.approvals.has_pending(request_id):
            exchange["task"].cancel()
            await asyncio.shield(exchange["task"])
        if exchange["task"].done():
            hearth._http_requests.pop(request_id, None)


if __name__ == "__main__":
    print("HTTP request ownership is process-local; approval waits expire after 600 seconds")
