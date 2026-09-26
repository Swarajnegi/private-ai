import "@fontsource/space-grotesk/400.css";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/ibm-plex-mono/400.css";
import "./style.css";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { createScene, type CoreState } from "./scene";
import { LocalVoice } from "./voice";
import {
  ask,
  json,
  token,
  setToken,
  type Turn,
  type Session,
  type Model,
} from "./api";

const $ = <T extends HTMLElement = HTMLElement>(id: string) =>
  document.getElementById(id) as T;
const safeMarkdown = (text: string) =>
  DOMPurify.sanitize(marked.parse(text, { async: false }) as string, {
    FORBID_TAGS: ["img", "audio", "video", "iframe", "style", "input", "form"],
    FORBID_ATTR: ["style"],
  });
const escape = (value: unknown) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ]!,
  );
const icon = (name: string) => {
  const paths: Record<string, string> = {
    plus: "M12 5v14M5 12h14",
    close: "m6 6 12 12M6 18 18 6",
    arrow: "M12 19V5m-6 6 6-6 6 6",
    mic: "M9 5a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0V5M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8",
    pause: "M9 5v14M15 5v14",
    reset: "M4 11a8 8 0 1 1 1 6M4 5v6h6",
    sound: "m4 10 4 0 5-4v12l-5-4H4zM17 9a5 5 0 0 1 0 6",
    settings: "M4 7h16M4 17h16M8 4v6m8 4v6",
    chevron: "m9 5 7 7-7 7",
  };
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.plus}"/></svg>`;
};
$("app").innerHTML = `
<a href="#prompt" class="skip">Skip to conversation</a>
<canvas id="universe" tabindex="0" aria-label="JARVIS particle core. Drag to orbit, scroll to zoom, Home to reset."></canvas>
<header><a class="wordmark" href="/" aria-label="JARVIS home">J<span>Λ</span>RVIS<small>PERSONAL INTELLIGENCE</small></a>
<nav aria-label="Workspace"><button id="nav-core" class="active"><em>01</em> Core</button><button id="nav-chat"><em>02</em> Conversation</button><button id="nav-history"><em>03</em> History</button><button id="nav-system"><em>04</em> System</button></nav>
<div class="header-tools"><button id="motion" class="icon" aria-label="Pause animation">${icon("pause")}</button><button id="settings-open" class="icon" aria-label="Connection settings">${icon("settings")}</button><span id="connection" class="connection">CONNECTING</span></div></header>
<main>
 <section id="scene-copy"><p class="eyebrow">01 / COGNITIVE FIELD</p><h1>J.A.R.V.I.S</h1><p class="subhead">Personal intelligence.</p></section>
 <div class="scene-coordinate" aria-hidden="true"><span>PERSONAL / PRIVATE / PRESENT</span><span>DRAG TO ORBIT · SCROLL TO EXPLORE</span></div>
 <section id="conversation" class="conversation" aria-label="Conversation" hidden>
  <div class="panel-heading"><div><p class="eyebrow">02 / CONVERSATION</p><h2 id="chat-title">A new thought</h2></div><button id="new-chat" class="icon" aria-label="New conversation">${icon("plus")}</button><button id="export" class="text-button">Export</button><button id="close-chat" class="icon" aria-label="Close conversation">${icon("close")}</button></div>
  <div id="notice" role="status" hidden></div><div id="messages" tabindex="0" aria-label="Conversation messages"><div class="empty"><span>Begin anywhere.</span><p>Bring a question, an unfinished thought,<br>or something worth remembering.</p></div></div><button id="latest" hidden>↓ Latest reply</button>
 </section>
 <div id="dock" class="dock"><div class="live-state"><span id="state-dot"></span><span id="state" role="status">Awaiting connection</span><time id="elapsed"></time><button id="stop-waiting" hidden title="Disconnect this response stream. JARVIS may still finish and save its answer.">Stop waiting</button><button id="voice-stop" hidden>End voice</button></div>
 <form id="composer" novalidate><label class="sr-only" for="prompt">Message JARVIS</label><textarea id="prompt" rows="1" placeholder="Speak your mind. Or type it." style="resize:none"></textarea>
 <div class="compose-tools"><button id="model-picker" type="button" aria-haspopup="dialog"><span class="model-orbit">✧</span><span id="model-label">Choose intelligence</span><span class="down">⌄</span></button><div class="compose-right"><button id="configure" type="button" class="icon" aria-label="Configure request">${icon("settings")}</button><button id="mic" type="button" class="icon" aria-label="Start push-to-talk">${icon("mic")}</button><button id="handsfree" type="button" class="text-button">Hands-free</button><button id="send" type="submit" aria-label="Send message">${icon("arrow")}</button></div></div></form>
 <div class="dock-foot"><span id="privacy">LOCAL WORKSPACE · AUDIO STAYS HERE</span><span>ENTER TO SEND <b>/</b> SHIFT ENTER FOR A NEW LINE</span></div></div>
</main><footer><span>J.A.R.V.I.S <b>/</b> YOUR MIND, EXTENDED</span><button id="reset-view">RESET VIEW ↗</button><span id="health-time">HEARTH · NO SAMPLE</span></footer>
<dialog id="history" aria-labelledby="history-title"><div class="panel-heading"><div><p class="eyebrow">03 / ARCHIVE</p><h2 id="history-title">Conversations <small id="session-count"></small></h2></div><button class="icon" data-close aria-label="Close history">${icon("close")}</button></div><div class="search-wrap"><input id="search" type="search" placeholder="Search conversations" aria-label="Search conversations"><button id="clear-search" hidden aria-label="Clear search">×</button></div><div id="sessions"></div></dialog>
<dialog id="models" aria-labelledby="models-title"><div class="panel-heading"><div><p class="eyebrow">CHOOSE YOUR INTELLIGENCE</p><h2 id="models-title">Models</h2></div><button class="icon" data-close aria-label="Close models">${icon("close")}</button></div><input id="model-search" type="search" aria-label="Search models" placeholder="Search model or provider"><div id="model-list"></div><p class="fine">Paid models use your existing provider balance. Catalog prices are estimates per million tokens, not a spending cap.</p></dialog>
<dialog id="system" aria-labelledby="system-title"><div class="panel-heading"><div><p class="eyebrow">04 / THE HEARTH</p><h2 id="system-title">System activity</h2></div><button class="icon" data-close aria-label="Close system">${icon("close")}</button></div><canvas id="pulse" aria-label="Measured hearth response history"></canvas><p id="system-status">No live data</p><div id="metrics"></div><div id="jobs"></div><details><summary>Execution trace</summary><pre id="trace">No request in this session.</pre></details></dialog>
<dialog id="settings" aria-labelledby="settings-title"><form id="connection-form" novalidate><div class="panel-heading"><div><p class="eyebrow">PRIVATE CONNECTION</p><h2 id="settings-title">Connect to JARVIS</h2></div><button class="icon" type="button" data-close aria-label="Close settings">${icon("close")}</button></div><p>Use this hearth’s token. It stays in this browser tab, not in a URL or your Git repository.</p><label for="token">Hearth token</label><input id="token" type="password" autocomplete="off" aria-describedby="auth-error"><label for="token-file">Or select your local token file</label><input id="token-file" type="file"><p id="auth-error" role="alert"></p><button class="primary" type="submit">Connect workspace ↗</button></form></dialog>
<dialog id="config" aria-labelledby="config-title"><div class="panel-heading"><h2 id="config-title">Request settings</h2><button class="icon" data-close aria-label="Close request settings">${icon("close")}</button></div><label for="reasoning">Reasoning</label><select id="reasoning"><option value="">Model default</option><option>low</option><option>medium</option><option>high</option></select><label for="tools">Tools</label><select id="tools"><option value="default">Standard toolkit</option><option value="full">Full toolkit</option></select><label class="checkbox"><input id="allow-all" type="checkbox">Allow gated tools for this request</label><p class="fine">Enables code, shell and file actions. This choice does not remove JARVIS’s backend permissions.</p></dialog>
<div id="toast" role="status" hidden></div>`;

const core = createScene($<HTMLCanvasElement>("universe"));
new ResizeObserver(([entry]) => {
  document.documentElement.style.setProperty(
    "--dock-height",
    `${entry.contentRect.height}px`,
  );
}).observe($("dock"));
let sessions: Session[] = [],
  messages: Turn[] = [],
  models: Model[] = [],
  session = new URL(location.href).searchParams.get("session"),
  busy = false,
  online = false,
  loading = 0,
  selected = localStorage.getItem("jarvis.model") || "openrouter/free",
  controller: AbortController | undefined,
  healthInFlight = false;
let activeVoice = false;
function status(text: string, state: CoreState) {
  $("state").textContent = text;
  $("state-dot").dataset.state = state;
  core.setState(state);
}
function notice(text = "") {
  $("notice").textContent = text;
  $("notice").hidden = !text;
}
function toast(text: string) {
  $("toast").textContent = text;
  $("toast").hidden = false;
  setTimeout(() => ($("toast").hidden = true), 5000);
}
function chat(open = true) {
  $("conversation").hidden = !open;
  document.body.classList.toggle("chat-open", open);
  core.setPanel(open);
  $("nav-chat").classList.toggle("active", open);
  $("nav-core").classList.toggle("active", !open);
}
function modal(id: string) {
  const d = $<HTMLDialogElement>(id);
  const prior = document.activeElement as HTMLElement;
  d.showModal();
  document.body.classList.add("modal-open");
  d.addEventListener(
    "close",
    () => {
      document.body.classList.remove("modal-open");
      prior?.focus();
    },
    { once: true },
  );
}
document
  .querySelectorAll("[data-close]")
  .forEach((b) =>
    b.addEventListener("click", () => b.closest("dialog")?.close()),
  );
function draftKey() {
  return `jarvis.draft.${session || "new"}`;
}
function saveDraft() {
  localStorage.setItem(draftKey(), $<HTMLTextAreaElement>("prompt").value);
}
function restoreDraft() {
  $<HTMLTextAreaElement>("prompt").value =
    localStorage.getItem(draftKey()) || "";
}
function remember(id: string | null) {
  session = id;
  const url = new URL(location.href);
  if (id) url.searchParams.set("session", id);
  else url.searchParams.delete("session");
  history.replaceState({}, "", url);
}
function stopVoice() {
  activeVoice = false;
  voice.stop();
  $("voice-stop").hidden = true;
  $("mic").setAttribute("aria-pressed", "false");
  status(
    online ? "Ready when you are" : "Hearth disconnected",
    online ? "idle" : "offline",
  );
}
const voice = new LocalVoice(
  (text, state) => {
    if (state === "idle" && !voice.handsFree) activeVoice = false;
    status(text, state);
    $("voice-stop").hidden = state === "idle" && !voice.handsFree;
  },
  (n) => core.setAmplitude(n),
  async (text, send) => {
    $<HTMLTextAreaElement>("prompt").value = text;
    saveDraft();
    chat();
    if (send) await submit();
    else status("Transcript ready · review and send", "idle");
  },
);
function renderMessages(follow = true) {
  const region = $("messages");
  const previousScroll = region.scrollTop;
  const nearBottom =
    region.scrollHeight - region.clientHeight - previousScroll < 100;
  region.replaceChildren();
  for (const [i, m] of messages.entries()) {
    const article = document.createElement("article");
    article.className = `message ${m.role}`;
    const heading = document.createElement("div");
    heading.className = "message-heading";
    heading.innerHTML = `<span class="avatar">${m.role === "user" ? "S" : "J"}</span><strong>${m.role === "user" ? "YOU" : "JARVIS"}</strong><time>${m.ts ? escape(new Date(m.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })) : ""}</time>`;
    const actions = document.createElement("div");
    actions.className = "message-actions";
    for (const action of [
      "Copy",
      "Raw",
      ...(m.role === "assistant" ? ["Listen"] : []),
    ]) {
      const button = document.createElement("button");
      button.textContent = action;
      button.onclick = () => {
        if (action === "Copy")
          navigator.clipboard
            .writeText(m.content)
            .then(() => toast("Copied in full"))
            .catch(() =>
              toast("Clipboard unavailable. Export this conversation."),
            );
        if (action === "Raw") {
          const raw = content.classList.toggle("raw");
          content.innerHTML = raw ? "" : safeMarkdown(m.content);
          if (raw) content.textContent = m.content;
        }
        if (action === "Listen") {
          stopVoice();
          activeVoice = true;
          $("voice-stop").hidden = false;
          void voice.speak(m.content);
        }
      };
      actions.append(button);
    }
    heading.append(actions);
    const content = document.createElement("div");
    content.className = "message-content";
    if (m.role === "user") content.textContent = m.content;
    else content.innerHTML = safeMarkdown(m.content);
    content.querySelectorAll("a").forEach((a) => {
      a.rel = "noopener noreferrer";
      a.target = "_blank";
    });
    content.querySelectorAll("table").forEach((table) => {
      const wrap = document.createElement("div");
      wrap.className = "table-wrap";
      table.replaceWith(wrap);
      wrap.append(table);
    });
    article.dataset.turn = String(i);
    article.append(heading, content);
    region.append(article);
  }
  region.scrollTop =
    follow || nearBottom ? region.scrollHeight : previousScroll;
  $("latest").hidden = follow || nearBottom;
}
async function loadSessions() {
  sessions = (await json("/v1/sessions")).sessions || [];
  sessions.sort(
    (a, b) =>
      (Date.parse(b.latest_ts || "") || b.mtime * 1000) -
        (Date.parse(a.latest_ts || "") || a.mtime * 1000) ||
      b.session_id.localeCompare(a.session_id),
  );
  renderSessions();
}
function renderSessions() {
  const q = $<HTMLInputElement>("search").value.toLowerCase();
  $("clear-search").hidden = !q;
  $("session-count").textContent = String(sessions.length);
  $("sessions").replaceChildren();
  for (const s of sessions.filter((s) =>
    `${s.title} ${s.first_prompt || ""}`.toLowerCase().includes(q),
  )) {
    const b = document.createElement("button");
    b.className = "session";
    b.innerHTML = `<strong>${escape(s.title || "Untitled")}</strong><small>${s.turn_count} messages · ${escape(new Date(s.latest_ts || s.mtime * 1000).toLocaleString())}</small>`;
    b.onclick = () => void openSession(s.session_id);
    $("sessions").append(b);
  }
  if (!$("sessions").children.length)
    $("sessions").textContent = q
      ? "No matching conversations."
      : "Your first conversation starts here.";
}
async function openSession(id: string) {
  if (busy)
    return toast("A response is in progress. Please wait for it to finish.");
  const revision = ++loading;
  stopVoice();
  try {
    const data = await json(`/v1/sessions/${encodeURIComponent(id)}`);
    if (revision !== loading) return;
    saveDraft();
    remember(id);
    messages = data.messages || [];
    renderMessages();
    restoreDraft();
    $("chat-title").textContent =
      sessions.find((s) => s.session_id === id)?.title || "Conversation";
    $<HTMLDialogElement>("history").close();
    chat();
    notice();
  } catch (e) {
    toast((e as Error).message);
  }
}
function renderModels() {
  const q = $<HTMLInputElement>("model-search").value.toLowerCase();
  $("model-list").replaceChildren();
  for (const free of [true, false]) {
    const rows = models.filter(
      (m) =>
        Boolean(m.free) === free &&
        `${m.id} ${m.name}`.toLowerCase().includes(q),
    );
    if (!rows.length) continue;
    const h = document.createElement("h3");
    h.textContent = free ? "FREE MODELS" : "PAID · PROVIDER BALANCE";
    $("model-list").append(h);
    for (const m of rows) {
      const b = document.createElement("button");
      b.className = "model-option";
      b.setAttribute("aria-pressed", String(m.id === selected));
      b.innerHTML = `<span>${escape(m.name || m.id)}<small>${escape(m.id)}${m.free ? " · Free" : ` · $${escape(m.cost_input_1m)} in / $${escape(m.cost_output_1m)} out`}</small></span><span>${m.id === selected ? "✓" : "↗"}</span>`;
      b.onclick = () => {
        selected = String(m.id);
        localStorage.setItem("jarvis.model", selected);
        $("model-label").textContent = String(m.name || m.id);
        $<HTMLDialogElement>("models").close();
      };
      $("model-list").append(b);
    }
  }
  if (!$("model-list").children.length)
    $("model-list").textContent = "No matching models.";
}
async function loadModels() {
  models = (await json("/v1/models")).models || [];
  if (!models.length)
    throw Error("The hearth returned an empty model catalog.");
  $("model-label").textContent = String(
    models.find((m) => m.id === selected)?.name || selected,
  );
  renderModels();
}
const beats: { latency: number; ok: boolean }[] = [];
async function health() {
  if (!token || healthInFlight) return;
  healthInFlight = true;
  const start = performance.now();
  try {
    const h = await json("/v1/health");
    online = true;
    const failed = (h.jobs || []).some((j: any) =>
      /^(error|fail)/i.test(j.status || ""),
    );
    $("connection").textContent = failed
      ? "NEEDS ATTENTION"
      : "LOCAL / CONNECTED";
    $("connection").dataset.ok = String(!failed);
    const latency = Math.round(performance.now() - start);
    $("health-time").textContent = `HEARTH / ${latency} MS`;
    $("system-status").textContent =
      `${h.busy ? "Processing a request" : "Connected"} · ${Math.floor(h.uptime_seconds / 60)} min uptime`;
    beats.push({ latency, ok: !failed });
    if (!busy && !voice.recording && !activeVoice)
      status(
        failed ? "A background job needs attention" : "Ready when you are",
        "idle",
      );
    $("metrics").innerHTML =
      `<div>Conversations <strong>${sessions.length}</strong></div><div>Requests this run <strong>${h.requests_served}</strong></div>`;
    $("jobs").innerHTML = (h.jobs || [])
      .map(
        (j: any) =>
          `<div class="job"><span>${escape(j.name.replaceAll("_", " "))}</span><small>${escape(j.status)}</small></div>`,
      )
      .join("");
  } catch {
    online = false;
    $("connection").textContent = "DISCONNECTED";
    $("connection").dataset.ok = "false";
    $("health-time").textContent = "HEARTH / UNAVAILABLE";
    $("system-status").textContent =
      "Health check failed. No current telemetry.";
    $("metrics").replaceChildren();
    $("jobs").replaceChildren();
    beats.push({ latency: 0, ok: false });
    if (!busy && !activeVoice) status("Hearth disconnected", "offline");
  } finally {
    healthInFlight = false;
    while (beats.length > 32) beats.shift();
    drawPulse();
  }
}
function drawPulse() {
  const c = $<HTMLCanvasElement>("pulse"),
    ctx = c.getContext("2d")!;
  c.width = 600;
  c.height = 160;
  ctx.clearRect(0, 0, 600, 160);
  ctx.strokeStyle = "#293746";
  ctx.beginPath();
  ctx.moveTo(0, 100);
  ctx.lineTo(600, 100);
  ctx.stroke();
  beats.forEach((b, i) => {
    const x = 20 + i * 18;
    ctx.strokeStyle = b.ok ? "#69baff" : "#ff7185";
    ctx.beginPath();
    ctx.moveTo(x - 5, 100);
    ctx.lineTo(x, 100 - Math.min(75, 10 + b.latency / 4));
    ctx.lineTo(x + 5, 100);
    ctx.stroke();
  });
}
async function submit() {
  const prompt = $<HTMLTextAreaElement>("prompt"),
    question = prompt.value.trim();
  if (!question || busy) return;
  if (!token) {
    modal("settings");
    return;
  }
  if (!voice.handsFree) voice.stop();
  ++loading;
  saveDraft();
  const oldKey = draftKey();
  if (!session) remember(`conv-web-${crypto.randomUUID()}`);
  const requestSession = session!;
  busy = true;
  $("stop-waiting").hidden = false;
  $<HTMLButtonElement>("send").disabled = true;
  chat();
  notice();
  messages.push({
    role: "user",
    content: question,
    ts: new Date().toISOString(),
  });
  renderMessages();
  $("chat-title").textContent =
    sessions.find((s) => s.session_id === session)?.title || question;
  prompt.value = "";
  localStorage.removeItem(oldKey);
  localStorage.removeItem(draftKey());
  status("JARVIS is thinking", "thinking");
  $("trace").textContent = "";
  controller = new AbortController();
  let final: any = null;
  const start = Date.now();
  const timer = setInterval(() => {
    $("elapsed").textContent = `${Math.floor((Date.now() - start) / 1000)}s`;
  }, 1000);
  try {
    await ask(
      {
        question,
        session: requestSession,
        model: selected,
        reasoning_effort: $<HTMLSelectElement>("reasoning").value || undefined,
        full: $<HTMLSelectElement>("tools").value === "full",
        allow_all: $<HTMLInputElement>("allow-all").checked,
      },
      (event, data) => {
        if (event === "answer") final = data;
        if (event === "log") {
          $("trace").append(
            document.createTextNode(String(data.line || "") + "\n"),
          );
        }
      },
      controller.signal,
    );
    if (!final?.ok)
      throw Error(
        final?.error ||
          "The stream ended without a final answer. Reload this conversation before retrying; the hearth may still save it.",
      );
    const answer: Turn = {
      role: "assistant",
      content: String(final.answer || ""),
      ts: new Date().toISOString(),
      telemetry: final,
    };
    messages.push(answer);
    renderMessages(false);
    if (final.persisted === false || final.degenerate)
      notice(
        "This response was not saved by the hearth. Export it if you need to keep it.",
      );
    else {
      try {
        const saved = await json(
          `/v1/sessions/${encodeURIComponent(requestSession)}`,
        );
        if (
          [...saved.messages]
            .reverse()
            .find((m: Turn) => m.role === "assistant")?.content !==
          answer.content
        )
          notice(
            "The saved answer differs. Export this complete response before leaving.",
          );
      } catch {
        notice(
          "Saved history could not be verified. Export this response before leaving.",
        );
      }
    }
    if (final.denials?.length)
      notice("Some tools require approval. Review Request settings.");
    if (activeVoice) void voice.speak(answer.content);
  } catch (e) {
    notice(
      controller?.signal.aborted
        ? "Stopped waiting. JARVIS may still finish and save this answer. Check history before retrying."
        : (e as Error).message,
    );
    prompt.value = question;
    saveDraft();
    stopVoice();
  } finally {
    clearInterval(timer);
    $("elapsed").textContent = "";
    busy = false;
    $("stop-waiting").hidden = true;
    $<HTMLButtonElement>("send").disabled = false;
    if (!activeVoice && !voice.recording && !voice.handsFree)
      status(
        online ? "Ready when you are" : "Hearth disconnected",
        online ? "idle" : "offline",
      );
    void health();
    void loadSessions().catch(() => {});
  }
}
$("messages").onscroll = () => {
  const r = $("messages");
  $("latest").hidden = r.scrollHeight - r.scrollTop - r.clientHeight < 100;
};
$("stop-waiting").onclick = () => controller?.abort();
$("latest").onclick = () => {
  $("messages").scrollTo({
    top: $("messages").scrollHeight,
    behavior: "smooth",
  });
};
$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  void submit();
});
$("prompt").addEventListener("input", saveDraft);
$("prompt").addEventListener("focus", () => chat());
$("prompt").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    void submit();
  }
});
$("nav-core").onclick = () => chat(false);
$("nav-chat").onclick = () => chat();
$("close-chat").onclick = () => chat(false);
$("nav-history").onclick = () => {
  renderSessions();
  modal("history");
};
$("nav-system").onclick = () => {
  modal("system");
  drawPulse();
};
$("settings-open").onclick = () => modal("settings");
$("model-picker").onclick = () => {
  renderModels();
  modal("models");
  $<HTMLInputElement>("model-search").focus();
};
$("configure").onclick = () => modal("config");
$("search").oninput = renderSessions;
$("clear-search").onclick = () => {
  $<HTMLInputElement>("search").value = "";
  renderSessions();
};
$("model-search").oninput = renderModels;
$("model-list").onkeydown = (e) => {
  if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
  e.preventDefault();
  const buttons = [
      ...$("model-list").querySelectorAll<HTMLButtonElement>("button"),
    ],
    i = buttons.indexOf(document.activeElement as HTMLButtonElement);
  buttons[
    e.key === "Home"
      ? 0
      : e.key === "End"
        ? buttons.length - 1
        : Math.max(
            0,
            Math.min(buttons.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)),
          )
  ]?.focus();
};
$("model-search").onkeydown = (e) => {
  if (e.key === "ArrowDown") {
    e.preventDefault();
    $("model-list").querySelector<HTMLButtonElement>("button")?.focus();
  }
};
$("new-chat").onclick = () => {
  if (busy)
    return toast(
      "Wait for the current answer before starting a new conversation.",
    );
  stopVoice();
  saveDraft();
  remember(null);
  messages = [];
  $("messages").replaceChildren();
  $("chat-title").textContent = "A new thought";
  restoreDraft();
  notice();
  chat();
  $<HTMLTextAreaElement>("prompt").focus();
};
$("motion").onclick = () => {
  const paused = core.toggle();
  $("motion").setAttribute(
    "aria-label",
    paused ? "Resume animation" : "Pause animation",
  );
  $("motion").setAttribute("aria-pressed", String(paused));
};
$("reset-view").onclick = () => core.reset();
$("mic").onclick = () => {
  if (busy) return toast("Wait for the current answer.");
  if (voice.recording) {
    void voice.finish();
    return;
  }
  stopVoice();
  activeVoice = true;
  $("voice-stop").hidden = false;
  void voice.start(false);
};
$("handsfree").onclick = () => {
  if (busy) return toast("Wait for the current answer.");
  stopVoice();
  activeVoice = true;
  $("voice-stop").hidden = false;
  void voice.start(true);
};
$("voice-stop").onclick = stopVoice;
$("export").onclick = () => {
  const blob = new Blob(
    [messages.map((m) => `## ${m.role}\n\n${m.content}`).join("\n\n")],
    { type: "text/markdown" },
  );
  const url = URL.createObjectURL(blob),
    a = document.createElement("a");
  a.href = url;
  a.download = `${session || "jarvis"}.md`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
$("token-file").onchange = async () => {
  const file = $<HTMLInputElement>("token-file").files?.[0];
  if (file) $<HTMLInputElement>("token").value = (await file.text()).trim();
};
$("connection-form").onsubmit = async (e) => {
  e.preventDefault();
  const candidate = $<HTMLInputElement>("token").value.trim(),
    prior = token;
  if (!candidate) {
    $("auth-error").textContent = "Enter a token or choose the token file.";
    return;
  }
  setToken(candidate);
  try {
    await json("/v1/auth/verify");
    $<HTMLInputElement>("token").value = "";
    $<HTMLDialogElement>("settings").close();
    await boot();
  } catch (e) {
    setToken(prior);
    $("auth-error").textContent = (e as Error).message;
  }
};
async function boot() {
  await health();
  await Promise.all([loadSessions(), loadModels()]).catch((e) =>
    toast(e.message),
  );
  if (session) await openSession(session);
  restoreDraft();
}
document.addEventListener("keydown", (e) => {
  if (document.querySelector("dialog[open]")) return;
  if (e.altKey && e.key.toLowerCase() === "n") {
    e.preventDefault();
    $("new-chat").click();
  }
  if (
    e.key === "/" &&
    !/INPUT|TEXTAREA|SELECT/.test((e.target as HTMLElement).tagName)
  ) {
    e.preventDefault();
    $("nav-history").click();
    $("search").focus();
  }
  if (e.key === "Escape" && !document.querySelector("dialog[open]"))
    chat(false);
});
for (const id of ["reasoning", "tools"]) {
  const control = $<HTMLSelectElement>(id);
  control.value = localStorage.getItem(`jarvis.${id}`) || control.value;
  control.onchange = () => localStorage.setItem(`jarvis.${id}`, control.value);
}
document.addEventListener("visibilitychange", () => {
  if (document.hidden && activeVoice) stopVoice();
  else if (!document.hidden) void health();
});
addEventListener("pagehide", () => voice.stop());
setInterval(() => {
  if (!document.hidden) void health();
}, 5000);
if (token) void boot();
else {
  status("Connect your local hearth", "offline");
  modal("settings");
}
