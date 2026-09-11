"""
hearth.py — one always-on process; every surface is a thin adapter to it.

LAYER: Brain (transport shell — no reasoning of its own)

Run with:
    python3 scripts/hearth.py                 # serve on 127.0.0.1:8756
    python3 -m jarvis_core.serve.hearth        # smoke tests (offline, no socket)

=============================================================================
THE BIG PICTURE
=============================================================================

Until now JARVIS had exactly one interface: `python3 -m ...orchestrator --ask`.
That single fact caused the deadlock recorded in ENDGAME §1.2 — the
consolidator ran only inside Mind's heartbeat, Mind booted only on --ask, and
--ask went unused for 35 days, so the organ that justifies the whole system
starved for lack of a pulse.

Without a hearth:
    -> every surface (phone, browser, IDE) would have to embed the mind, and
       five embedded copies of a mutable mind are five DIFFERENT minds.

With a hearth:
    -> ONE process holds the mutable state and the clock. Every surface becomes
       a socket client. "Same mind everywhere" stops being a sync problem and
       becomes a routing problem, which is a solved one.

WHY THIS IS NOT A DISTRIBUTED SYSTEM. The model is already an injected callable
(`llm_call`), not a resident thing, and the mind is ~6 MB of files. So there is
nothing to shard and nothing to replicate — just one owner and many mouths.

WHY RAW ASGI AND NOT FastAPI. `uvicorn` is already installed; fastapi and
starlette are not. An ASGI app is a plain async callable, so this file adds ZERO
dependencies and — more useful — is testable with a fake receive/send pair and
no socket at all. Every test below runs offline.

SAFETY POSTURE OF v0 (deliberately timid):
    - binds 127.0.0.1 only, and re-checks the peer address per request;
    - a bearer token is REQUIRED even on loopback, because loopback is not a
      boundary against other local processes or a stray browser page;
    - one request at a time (the mind has mutable session state), 409 otherwise;
    - every permission prompt is DENIED and REPORTED, never silently dropped.
      A daemon has no TTY, so a human gate cannot be honoured here; remote
      approval is the Commitment gate (step 10), not this.

=============================================================================
THE FLOW
=============================================================================

STEP 1: build_app() closes over a Hearth and returns an ASGI callable.
        |
STEP 2: A request arrives. _authorize() checks the peer is loopback and the
        bearer token matches (hmac.compare_digest — no early-exit leak).
        |
STEP 3: GET /v1/health answers from state alone — never boots the mind, so a
        liveness probe costs nothing.
        |
STEP 4: POST /v1/ask acquires the single-flight slot, then calls the SAME
        orchestrator.ask() the terminal calls, with printer= pointed at an
        asyncio.Queue instead of stdout.
        |
STEP 5: If the client sent Accept: text/event-stream, the queue is drained to
        SSE as the answer is built; otherwise it is collected and returned as
        one JSON body. Identical computation, two renderings.
        |
STEP 6: The AskResult's answer + verdict + ledger go out as the terminal event,
        so a streaming client never has to guess when it is done.
=============================================================================
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import secrets
import stat
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.config import DATA_ROOT

TOKEN_PATH = Path(DATA_ROOT) / ".hearth_token"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8756

_MAX_BODY_BYTES = 256 * 1024
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost", ""})
_SSE_PING_SECONDS = 15.0
_QUEUE_DRAIN_TIMEOUT = 0.5

Send = Callable[[Dict[str, Any]], Awaitable[None]]
Receive = Callable[[], Awaitable[Dict[str, Any]]]


# =============================================================================
# Part 1: TOKEN (a shared secret, on disk, 0600)
# =============================================================================

def ensure_token(path: Path = TOKEN_PATH) -> str:
    """Read the hearth token, minting one on first run. 0600, gitignored.

    EXECUTION FLOW:
    1. Existing non-empty file -> return its contents stripped.
    2. Otherwise mint 32 bytes of urlsafe randomness and write it 0600.

    Returns:
        The token string. Raises OSError only if jarvis_data is unwritable,
        which is a genuine stop — an unauthenticated hearth must not start.
    """
    path = Path(path)
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except (OSError, FileNotFoundError):
        pass
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass                                   # best effort (Windows/WSL mounts)
    return token


# =============================================================================
# Part 2: CONFIG + STATE
# =============================================================================

@dataclass(frozen=True)
class HearthConfig:
    """Everything the hearth needs to know before it binds a socket."""
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    token: str = ""
    ask_kwargs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _Denial:
    """A permission prompt the hearth refused because no human was reachable."""
    tool: str
    preview: str


# =============================================================================
# Part 3: THE HEARTH
# =============================================================================

class Hearth:
    """
    LAYER Brain: owns the single-flight slot, the request counters, and the
    bridge from orchestrator.ask()'s synchronous printer to an async stream.

    Purpose:
        - Serve /v1/ask over HTTP with the same code path as --ask.
        - Refuse concurrent asks instead of interleaving mutable session state.
        - Report every denied permission rather than swallowing it.

    How it works:
        ask() takes printer= and ask_handler= as parameters already, so the
        hearth injects its own: printer pushes onto an asyncio.Queue that the
        response drains, and the handler records-then-denies.
    """

    def __init__(
        self,
        config: HearthConfig,
        ask_fn: Optional[Callable[..., Awaitable[Any]]] = None,
        scheduler: Optional[Any] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._cfg = config
        self._ask_fn = ask_fn
        self._scheduler = scheduler
        self._clock = clock
        self._slot = asyncio.Semaphore(1)
        self._started_at = clock()
        self.requests_served = 0
        self.requests_rejected = 0
        self.last_error = ""

    # ---- ask() resolution (late import: keeps smoke tests offline) -------

    def _resolve_ask(self) -> Callable[..., Awaitable[Any]]:
        if self._ask_fn is not None:
            return self._ask_fn
        from jarvis_core.brain.orchestrator import ask
        return ask

    # ---- the run itself --------------------------------------------------

    async def run_ask(
        self, question: str, emit: Callable[[str, Dict[str, Any]], Awaitable[None]],
        session: Optional[str] = None, new_session: bool = False,
        targets: Optional[List[str]] = None,
        full: bool = False, allow_all: bool = False,
        max_iterations: Optional[int] = None, budget_usd: Optional[float] = None,
        reasoning_effort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """One spine pass, narrated through `emit`. Returns the final payload.

        EXECUTION FLOW:
        1. Build the queue-backed printer and the recording deny-handler.
        2. Launch ask() as a task; drain narration to `emit` while it runs.
        3. On completion, emit nothing more — return the terminal payload so
           the caller decides how to render it (SSE event vs JSON body).

        Returns:
            A JSON-safe dict: answer, verdict, confidence, denials, ledger.
        """
        queue: "asyncio.Queue[str]" = asyncio.Queue()
        denials: List[_Denial] = []

        def printer(line: str) -> None:
            queue.put_nowait(str(line))

        def deny_handler(tool_name: str, tool_input: Dict[str, Any]) -> Any:
            from jarvis_core.agent.permissions import PermissionDecision
            preview = str(tool_input)
            denials.append(_Denial(tool=str(tool_name), preview=preview[:200]))
            printer(f"  [permission] {tool_name} DENIED — no human is reachable "
                    f"over the hearth; run it from --ask if you want to approve it")
            return PermissionDecision.DENY

        if allow_all:
            from jarvis_core.brain.orchestrator import allow_all_ask_handler
            active_handler = allow_all_ask_handler
        else:
            active_handler = deny_handler

        kwargs: Dict[str, Any] = dict(self._cfg.ask_kwargs)
        kwargs.update(printer=printer, ask_handler=active_handler,
                      session=session, new_session=new_session)
        if targets:
            kwargs["targets"] = targets
        if full:
            kwargs["full"] = True
        if max_iterations is not None:
            kwargs["max_iterations"] = max_iterations
        if budget_usd is not None:
            kwargs["budget_usd"] = budget_usd
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort

        ask_fn = self._resolve_ask()
        task = asyncio.ensure_future(ask_fn(question, **kwargs))
        try:
            async for line in self._drain(queue, task):
                await emit("log", {"line": line})
            result = await task
        except Exception as e:                 # a crash is an answer, not a hang
            self.last_error = f"{type(e).__name__}: {e}"
            return {"ok": False, "error": self.last_error, "answer": "",
                    "denials": [d.tool for d in denials]}
        return self._payload(result, denials)

    @staticmethod
    async def _drain(queue: "asyncio.Queue[str]", task: "asyncio.Future[Any]"):
        """Yield narration lines until the task finishes AND the queue empties.

        The timeout is what makes this correct rather than merely working: a
        blocking get() would hang forever on the last line if ask() finished
        without printing again, and a bare empty() poll would spin the CPU.
        """
        while True:
            try:
                yield await asyncio.wait_for(queue.get(), timeout=_QUEUE_DRAIN_TIMEOUT)
            except asyncio.TimeoutError:
                if task.done() and queue.empty():
                    return
            except asyncio.CancelledError:
                raise

    @staticmethod
    def _payload(result: Any, denials: List[_Denial]) -> Dict[str, Any]:
        """AskResult -> a JSON-safe dict. Unknown shapes degrade, never raise."""
        get = lambda name, default: getattr(result, name, default)  # noqa: E731
        ledger = get("ledger", {}) or {}
        return {
            "ok": True,
            "question": str(get("question", "")),
            "answer": str(get("answer", "")),
            "verdict": str(get("verdict", "")),
            "confidence": float(get("confidence_score", 0.0) or 0.0),
            "grounds": [str(g) for g in (get("grounds", ()) or ())],
            "reasoning_verdict": str(get("reasoning_verdict", "")),
            "conflict_detected": bool(get("conflict_detected", False)),
            "denials": [{"tool": d.tool, "preview": d.preview} for d in denials],
            "ledger": {k: v for k, v in ledger.items()
                       if isinstance(v, (str, int, float, bool, type(None)))},
        }

    # ---- authorization ---------------------------------------------------

    def authorize(self, scope: Dict[str, Any]) -> Optional[str]:
        """None when the request may proceed, else the reason to refuse.

        Two independent checks, because either alone is insufficient: the peer
        must be loopback (so a misconfigured bind cannot expose the mind), AND
        the bearer token must match (so another local process cannot use it).
        """
        client = scope.get("client") or ("", 0)
        host = str(client[0] if isinstance(client, (list, tuple)) and client else "")
        if host not in _LOOPBACK:
            return f"non-loopback client {host}"
        supplied = ""
        for key, value in scope.get("headers", []):
            if key.lower() == b"authorization":
                raw = value.decode("latin-1")
                supplied = raw[7:].strip() if raw[:7].lower() == "bearer " else raw.strip()
                break
        if not self._cfg.token:
            return "hearth has no token configured"
        if not supplied or not hmac.compare_digest(supplied, self._cfg.token):
            return "bad or missing bearer token"
        return None

    # ---- health ----------------------------------------------------------

    def health(self) -> Dict[str, Any]:
        """State-only snapshot. Never boots the mind — a probe must be free."""
        jobs = []
        if self._scheduler is not None:
            try:
                jobs = self._scheduler.status()
            except Exception:
                jobs = []
        return {
            "ok": True,
            "uptime_seconds": round(self._clock() - self._started_at, 1),
            "pid": os.getpid(),
            "busy": self._slot.locked(),
            "requests_served": self.requests_served,
            "requests_rejected": self.requests_rejected,
            "last_error": self.last_error,
            "jobs": jobs,
        }


# =============================================================================
# Part 4: THE ASGI APP
# =============================================================================

def _json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


async def _respond(send: Send, status: int, body: bytes,
                   content_type: bytes = b"application/json") -> None:
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", content_type),
                            (b"content-length", str(len(body)).encode()),
                            (b"cache-control", b"no-store")]})
    await send({"type": "http.response.body", "body": body})


async def _read_body(receive: Receive) -> bytes:
    """Collect the request body with a hard cap. Oversize raises ValueError."""
    chunks: List[bytes] = []
    total = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            raise ConnectionError("client disconnected before the body arrived")
        chunk = message.get("body", b"") or b""
        total += len(chunk)
        if total > _MAX_BODY_BYTES:
            raise ValueError(f"body exceeds {_MAX_BODY_BYTES} bytes")
        chunks.append(chunk)
        if not message.get("more_body"):
            return b"".join(chunks)


def _wants_stream(scope: Dict[str, Any]) -> bool:
    for key, value in scope.get("headers", []):
        if key.lower() == b"accept" and b"text/event-stream" in value.lower():
            return True
    return False


def _sse(event: str, data: Dict[str, Any]) -> bytes:
    """One SSE frame. Newlines in data would break framing, so JSON only."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


def build_app(hearth: Hearth) -> Callable[..., Awaitable[None]]:
    """Return an ASGI 3 application closed over `hearth`.

    EXECUTION FLOW:
    1. Non-HTTP scopes (lifespan, websocket) are answered minimally.
    2. Authorize -> 403 with a reason.
    3. Route: GET /v1/health, POST /v1/ask. Anything else 404.

    Returns:
        An `async def app(scope, receive, send)` callable uvicorn can serve.
    """

    async def app(scope: Dict[str, Any], receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope["type"] != "http":
            return

        refusal = hearth.authorize(scope)
        if refusal is not None:
            hearth.requests_rejected += 1
            await _respond(send, 403, _json_bytes({"ok": False, "error": refusal}))
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()

        if path in ("/v1/health", "/health") and method == "GET":
            await _respond(send, 200, _json_bytes(hearth.health()))
            return

        if path == "/v1/ask" and method == "POST":
            await _handle_ask(hearth, scope, receive, send)
            return

        await _respond(send, 404, _json_bytes(
            {"ok": False, "error": f"no route for {method} {path}",
             "routes": ["GET /v1/health", "POST /v1/ask"]}))

    return app


async def _handle_ask(hearth: Hearth, scope: Dict[str, Any],
                      receive: Receive, send: Send) -> None:
    """POST /v1/ask — single-flight, streaming or buffered."""
    try:
        raw = await _read_body(receive)
    except (ValueError, ConnectionError) as e:
        await _respond(send, 413 if isinstance(e, ValueError) else 400,
                       _json_bytes({"ok": False, "error": str(e)}))
        return
    try:
        body = json.loads(raw or b"{}")
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
    except (ValueError, json.JSONDecodeError) as e:
        await _respond(send, 400, _json_bytes({"ok": False, "error": f"bad JSON: {e}"}))
        return

    question = str(body.get("question", "")).strip()
    if not question:
        await _respond(send, 400, _json_bytes(
            {"ok": False, "error": "field 'question' is required and must be non-empty"}))
        return

    # Single-flight. Rejecting beats queueing: a client blocked for three
    # minutes behind someone else's question cannot tell that from a hang.
    if hearth._slot.locked():
        hearth.requests_rejected += 1
        await _respond(send, 409, _json_bytes(
            {"ok": False, "error": "hearth is busy with another question",
             "retry": "poll GET /v1/health until busy is false"}))
        return

    session = body.get("session")
    new_session = bool(body.get("new_session", False))
    model = body.get("model")
    targets = [str(model)] if model else body.get("targets")
    full = bool(body.get("full", False))
    allow_all = bool(body.get("allow_all", False))
    max_iterations = body.get("max_iterations")
    budget_usd = body.get("budget_usd")
    reasoning_effort = body.get("reasoning_effort")
    streaming = _wants_stream(scope)

    async with hearth._slot:
        hearth.requests_served += 1
        if not streaming:
            collected: List[str] = []

            async def collect(_event: str, data: Dict[str, Any]) -> None:
                if "line" in data:
                    collected.append(str(data["line"]))

            payload = await hearth.run_ask(question, collect,
                                           session=session, new_session=new_session,
                                           targets=targets, full=full, allow_all=allow_all,
                                           max_iterations=max_iterations, budget_usd=budget_usd,
                                           reasoning_effort=reasoning_effort)
            payload["log"] = collected
            await _respond(send, 200 if payload.get("ok") else 500, _json_bytes(payload))
            return

        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/event-stream"),
                                (b"cache-control", b"no-store"),
                                (b"connection", b"keep-alive"),
                                (b"x-accel-buffering", b"no")]})

        async def emit(event: str, data: Dict[str, Any]) -> None:
            await send({"type": "http.response.body", "body": _sse(event, data),
                        "more_body": True})

        await emit("open", {"question": question})
        payload = await hearth.run_ask(question, emit,
                                       session=session, new_session=new_session,
                                       targets=targets, full=full, allow_all=allow_all,
                                       max_iterations=max_iterations, budget_usd=budget_usd,
                                       reasoning_effort=reasoning_effort)
        await emit("answer", payload)
        await send({"type": "http.response.body", "body": b"", "more_body": False})


# =============================================================================
# Part 5: SERVING (the only place uvicorn is touched)
# =============================================================================

def serve(config: HearthConfig, scheduler: Optional[Any] = None) -> int:
    """Bind and serve until interrupted. Returns a process exit code."""
    import uvicorn

    hearth = Hearth(config, scheduler=scheduler)
    app = build_app(hearth)

    if scheduler is not None:
        original = app

        async def app_with_clock(scope: Dict[str, Any], receive: Receive, send: Send) -> None:
            if scope["type"] == "lifespan":
                while True:
                    message = await receive()
                    if message["type"] == "lifespan.startup":
                        scheduler.start()
                        await send({"type": "lifespan.startup.complete"})
                    elif message["type"] == "lifespan.shutdown":
                        await scheduler.stop()
                        await send({"type": "lifespan.shutdown.complete"})
                        return
            else:
                await original(scope, receive, send)

        app = app_with_clock

    uvicorn.run(app, host=config.host, port=config.port,
                log_level="warning", access_log=False)
    return 0


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (offline — no socket, no LLM, no writes)
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  hearth.py -- Smoke Tests (offline: fake ASGI, scripted ask)")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
            print(f"  PASS  {name}")
        else:
            failed.append(name)
            print(f"  FAIL  {name}  {hint}")

    class FakeResult:
        question = "q"
        answer = "the answer"
        verdict = "GROUNDED"
        confidence_score = 0.91
        grounds = ("because",)
        reasoning_verdict = "SOUND"
        conflict_detected = False
        ledger = {"model": "fake", "cost_usd": 0.0, "nested": {"dropped": True}}

    async def scripted_ask(question: str, **kwargs: Any) -> FakeResult:
        printer = kwargs.get("printer") or (lambda _l: None)
        printer("  brain   : fake")
        printer(f"  query   : {question}")
        await asyncio.sleep(0)
        printer("  JARVIS  : the answer")
        return FakeResult()

    async def exploding_ask(question: str, **kwargs: Any) -> FakeResult:
        raise RuntimeError("provider down")

    def drive(app: Any, scope: Dict[str, Any], body: bytes = b"") -> Tuple[List[Dict[str, Any]], None]:
        """Run one request against an ASGI app; collect the sent messages."""
        sent: List[Dict[str, Any]] = []
        delivered = {"done": False}

        async def receive() -> Dict[str, Any]:
            if delivered["done"]:
                return {"type": "http.disconnect"}
            delivered["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message: Dict[str, Any]) -> None:
            sent.append(message)

        asyncio.get_event_loop().run_until_complete(app(scope, receive, send))
        return sent, None

    def http_scope(method: str, path: str, token: str = "tok",
                   accept: bytes = b"application/json",
                   client: Tuple[str, int] = ("127.0.0.1", 5555)) -> Dict[str, Any]:
        return {"type": "http", "method": method, "path": path, "client": client,
                "headers": [(b"authorization", f"Bearer {token}".encode()),
                            (b"accept", accept)]}

    def status_of(sent: List[Dict[str, Any]]) -> int:
        for m in sent:
            if m["type"] == "http.response.start":
                return int(m["status"])
        return 0

    def body_of(sent: List[Dict[str, Any]]) -> bytes:
        return b"".join(m.get("body", b"") for m in sent
                        if m["type"] == "http.response.body")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    cfg = HearthConfig(token="tok")
    hearth = Hearth(cfg, ask_fn=scripted_ask)
    app = build_app(hearth)

    # T1-T2: health is free and never touches the mind.
    sent, _ = drive(app, http_scope("GET", "/v1/health"))
    health = json.loads(body_of(sent))
    check("T1 health returns 200 without booting anything", status_of(sent) == 200)
    check("T2 health reports pid, uptime and busy=False",
          health["pid"] == os.getpid() and health["busy"] is False, str(health)[:80])

    # T3-T5: authorization is two independent gates.
    sent, _ = drive(app, http_scope("GET", "/v1/health", token="wrong"))
    check("T3 a wrong bearer token is refused with 403", status_of(sent) == 403)
    sent, _ = drive(app, http_scope("GET", "/v1/health", client=("10.0.0.9", 1)))
    check("T4 a non-loopback peer is refused even WITH the right token",
          status_of(sent) == 403 and b"non-loopback" in body_of(sent))
    open_hearth = Hearth(HearthConfig(token=""), ask_fn=scripted_ask)
    sent, _ = drive(build_app(open_hearth), http_scope("GET", "/v1/health", token=""))
    check("T5 a hearth with no token refuses everything (fails closed)",
          status_of(sent) == 403, body_of(sent)[:60].decode())

    # T6-T8: the buffered ask path.
    sent, _ = drive(app, http_scope("POST", "/v1/ask"),
                    body=_json_bytes({"question": "what is 2+2"}))
    payload = json.loads(body_of(sent))
    check("T6 POST /v1/ask returns the answer", payload["answer"] == "the answer",
          str(payload)[:90])
    check("T7 the narration is captured, not discarded",
          any("query" in line for line in payload["log"]), str(payload.get("log"))[:80])
    check("T8 non-scalar ledger values are dropped, not crashed on",
          "nested" not in payload["ledger"] and payload["ledger"]["model"] == "fake",
          str(payload["ledger"]))

    # T9-T11: input validation.
    sent, _ = drive(app, http_scope("POST", "/v1/ask"), body=b"{not json")
    check("T9 malformed JSON is a 400, never a 500", status_of(sent) == 400)
    sent, _ = drive(app, http_scope("POST", "/v1/ask"), body=_json_bytes({"question": "  "}))
    check("T10 an empty question is refused with a reason",
          status_of(sent) == 400 and b"required" in body_of(sent))
    sent, _ = drive(app, http_scope("POST", "/v1/ask"),
                    body=_json_bytes({"question": "x" * (_MAX_BODY_BYTES + 10)}))
    check("T11 an oversized body is a 413, not an OOM", status_of(sent) == 413)

    # T12: unknown routes name what DOES exist.
    sent, _ = drive(app, http_scope("GET", "/v1/nope"))
    check("T12 an unknown route 404s and lists the real routes",
          status_of(sent) == 404 and b"/v1/ask" in body_of(sent))

    # T13-T14: SSE framing.
    sent, _ = drive(app, http_scope("POST", "/v1/ask", accept=b"text/event-stream"),
                    body=_json_bytes({"question": "stream me"}))
    stream = body_of(sent).decode()
    check("T13 SSE sets the event-stream content type",
          any(m["type"] == "http.response.start"
              and (b"content-type", b"text/event-stream") in m["headers"] for m in sent))
    check("T14 the stream carries log frames AND a terminal answer frame",
          "event: log" in stream and "event: answer" in stream
          and '"answer": "the answer"' in stream, stream[:120])

    # T15: a crash in ask() becomes an answer, not a hang.
    boom = Hearth(HearthConfig(token="tok"), ask_fn=exploding_ask)
    sent, _ = drive(build_app(boom), http_scope("POST", "/v1/ask"),
                    body=_json_bytes({"question": "explode"}))
    crashed = json.loads(body_of(sent))
    check("T15 an exception inside ask() returns 500 with the error named",
          status_of(sent) == 500 and "provider down" in crashed["error"], str(crashed)[:90])

    # T16: single-flight. The slot is held while a slow ask runs.
    async def slow_ask(question: str, **kwargs: Any) -> FakeResult:
        await asyncio.sleep(0.25)
        return FakeResult()

    busy = Hearth(HearthConfig(token="tok"), ask_fn=slow_ask)
    busy_app = build_app(busy)

    async def concurrent() -> Tuple[int, int]:
        results: List[int] = []

        async def one() -> None:
            sent_local: List[Dict[str, Any]] = []
            done = {"d": False}

            async def receive() -> Dict[str, Any]:
                if done["d"]:
                    return {"type": "http.disconnect"}
                done["d"] = True
                return {"type": "http.request",
                        "body": _json_bytes({"question": "q"}), "more_body": False}

            async def send(m: Dict[str, Any]) -> None:
                sent_local.append(m)

            await busy_app(http_scope("POST", "/v1/ask"), receive, send)
            results.append(status_of(sent_local))

        first = asyncio.ensure_future(one())
        await asyncio.sleep(0.05)               # let the first take the slot
        await one()
        await first
        return results[0], results[1]

    second, first = loop.run_until_complete(concurrent())
    check("T16 a concurrent ask is refused with 409, not interleaved",
          409 in (first, second) and 200 in (first, second), f"{first},{second}")
    check("T17 the rejection is counted", busy.requests_rejected >= 1,
          str(busy.requests_rejected))

    # T18-T19: permission prompts are denied AND reported.
    async def dangerous_ask(question: str, **kwargs: Any) -> FakeResult:
        handler = kwargs["ask_handler"]
        decision = handler("shell_run", {"command": "rm -rf /"})
        # repr(), not str() or an f-string: PermissionDecision subclasses str, so
        # f"{d}" renders "deny" (str.__format__) while str(d) renders
        # "PermissionDecision.DENY" (Enum.__str__). repr() is unambiguous.
        kwargs["printer"](f"  decision: {decision!r}")
        return FakeResult()

    gated = Hearth(HearthConfig(token="tok"), ask_fn=dangerous_ask)
    sent, _ = drive(build_app(gated), http_scope("POST", "/v1/ask"),
                    body=_json_bytes({"question": "delete everything"}))
    gated_payload = json.loads(body_of(sent))
    check("T18 a permission prompt over the hearth resolves to DENY",
          any("PermissionDecision.DENY" in line for line in gated_payload["log"]),
          str(gated_payload["log"])[:140])
    check("T19 the denial is REPORTED in the response, not swallowed",
          gated_payload["denials"]
          and gated_payload["denials"][0]["tool"] == "shell_run",
          str(gated_payload["denials"])[:80])

    # T20-T22: the token file.
    with tempfile.TemporaryDirectory() as td:
        tpath = Path(td) / ".hearth_token"
        first_token = ensure_token(tpath)
        check("T20 a token is minted on first use", len(first_token) >= 32, first_token[:8])
        check("T21 the same token is returned on the next call",
              ensure_token(tpath) == first_token)
        mode = stat.S_IMODE(tpath.stat().st_mode)
        check("T22 the token file is 0600", mode == 0o600, oct(mode))

    # T23: lifespan is answered, so uvicorn can actually start the app.
    async def lifespan() -> List[str]:
        got: List[str] = []
        messages = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]

        async def receive() -> Dict[str, Any]:
            return messages.pop(0)

        async def send(m: Dict[str, Any]) -> None:
            got.append(m["type"])

        await app({"type": "lifespan"}, receive, send)
        return got

    check("T23 lifespan startup and shutdown both complete",
          loop.run_until_complete(lifespan())
          == ["lifespan.startup.complete", "lifespan.shutdown.complete"])

    loop.close()
    print("-" * 70)
    print(f"  {passed} passed, {len(failed)} failed")
    if failed:
        for name in failed:
            print(f"    - {name}")
    print("=" * 70)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    _run_self_test()
