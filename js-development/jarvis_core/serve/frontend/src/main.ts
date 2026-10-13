/**
 * J.A.R.V.I.S — the core UI.
 *
 * Wiring only: the hearth owns conversations and state; Live mirrors the voice
 * socket; Field renders the core. Nothing here invents a reply, a status or a
 * number — every piece of text on screen came from the hearth.
 */
import "./style.css";
import DOMPurify from "dompurify";
import { marked } from "marked";
import * as api from "./api";
import { Field } from "./field";
import { Live, type CoreState } from "./live";
import { SessionsView } from "./sessions";
import { SystemView } from "./system";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

const WHISPER: Record<CoreState, string> = {
  waking: "Waking the core",
  idle: "Idle — type below, or turn on hands-free",
  listening: "Listening",
  transcribing: "Transcribing",
  thinking: "Thinking",
  speaking: "Speaking",
};
const PILL: Record<CoreState, string> = {
  waking: "idle", idle: "idle", listening: "listening",
  transcribing: "thinking", thinking: "thinking", speaking: "speaking",
};

const TITLE: Record<CoreState, string> = {
  waking: "Waking.", idle: "Idle.", listening: "Listening.",
  transcribing: "Hearing you.", thinking: "Thinking.", speaking: "Speaking.",
};

function toggleDialogue(): void {
  const folded = document.body.classList.toggle("dialogue-folded");
  $("dialogue-toggle").setAttribute("aria-expanded", String(!folded));
  setTimeout(() => layout(), 20);
}

/** A session's sigil: a small constellation of grains seeded by its id, so each
 *  conversation has its own mark. Decorative, and honest about it — it encodes
 *  identity only, never a fake measurement. */
function sigil(id: string): HTMLCanvasElement {
  const c = document.createElement("canvas");
  const dpr = Math.min(devicePixelRatio || 1, 2);
  c.width = 240 * dpr;
  c.height = 110 * dpr;
  c.className = "sigil";
  c.setAttribute("aria-hidden", "true");
  const g = c.getContext("2d")!;
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) h = Math.imul(h ^ id.charCodeAt(i), 16777619);
  const rnd = () => ((h = Math.imul(h ^ (h >>> 15), 2246822507) ^ Math.imul(h ^ (h >>> 13), 3266489909)) >>> 0) / 4294967296;
  const hues = ["255,181,71", "242,242,240", "143,197,255", "255,120,150", "170,140,255"];
  const cx = 120 * dpr, cy = 55 * dpr, arms = 2 + Math.floor(rnd() * 3), tilt = rnd() * Math.PI;
  for (let i = 0; i < 520; i++) {
    const f = rnd(), arm = Math.floor(rnd() * arms);
    const th = tilt + (arm / arms) * Math.PI * 2 + f * (2.4 + rnd() * 0.6);
    const r = (6 + f * 46 + (rnd() - 0.5) * 9) * dpr;
    const x = cx + Math.cos(th) * r * 1.9, y = cy + Math.sin(th) * r * 0.62;
    const col = rnd() < 0.72 ? hues[0] : hues[1 + Math.floor(rnd() * 4)];
    g.fillStyle = `rgba(${col},${(0.25 + rnd() * 0.7) * (1 - f * 0.5)})`;
    const sz = (rnd() < 0.04 ? 1.8 : 0.9) * dpr;
    g.fillRect(x, y, sz, sz);
  }
  return c;
}

// ---- session -------------------------------------------------------------
const params = new URLSearchParams(location.search);
let session = params.get("session") || localStorage.getItem("jarvis.session") || api.newSessionId();
const remember = (id: string) => {
  session = id;
  localStorage.setItem("jarvis.session", id);
  $("session-id").textContent = id;
  $("session-id").title = id;
  const url = new URL(location.href);
  url.searchParams.set("session", id);
  history.replaceState(null, "", url.pathname + url.search + url.hash);
};
remember(session);

// ---- the field -------------------------------------------------------------
const canvas = $<HTMLCanvasElement>("field");
let field: Field | null = null;
if (Field.supported()) {
  try {
    field = new Field(canvas);
  } catch {
    field = null;
  }
}
if (!field) {
  canvas.hidden = true;
  $("field-fallback").hidden = false;
}

let speak = true;
let handsFree = false;
let freeOnly = false;
try {
  freeOnly = localStorage.getItem("jarvis.freeOnly") === "1";
} catch {
  /* storage blocked: default to paid-first */
}
const live = new Live(session, speak, freeOnly);
if (field) {
  field.levelSource = () =>
    live.state === "speaking" ? live.voiceLevel() : live.state === "listening" ? Math.min(1, live.micLevel * 9) : 0;
}

const layout = () => {
  const narrow = innerWidth <= 760;
  const folded = document.body.classList.contains("dialogue-folded");
  // A folded dialogue still shows a 64 px spine (style.css --drawer), not zero.
  const drawer = narrow ? 0 : folded ? 64 : $("dialogue").getBoundingClientRect().width;
  // Phones: the core owns the band between the HUD and the dialogue below.
  field?.setFocus((innerWidth - drawer) / 2, narrow ? innerHeight * 0.33 : innerHeight * 0.44);
};
addEventListener("resize", layout);

// Dim the core when another section is over it: the core never competes
// with text for attention, and never sits under it at full brightness.
const sections = ["core", "sessions", "system"].map((id) => $(id));
// Section height varies with records and expanded diagnostics; position owns selection.
let activeSection = "";
let sectionFrame = 0;
function queueSectionUpdate(): void {
  if (sectionFrame) return;
  sectionFrame = requestAnimationFrame(() => {
    sectionFrame = 0;
    const active = sections.filter((el) => el.getBoundingClientRect().top <= innerHeight * 0.3).at(-1) || sections[0];
    if (active.id === activeSection) return;
    activeSection = active.id;
    document.querySelectorAll<HTMLAnchorElement>(".acts a").forEach((a) =>
      a.setAttribute("aria-current", String(a.dataset.act === active.id)),
    );
    field?.setDim(active.id === "core" ? 1 : 0.22);
    if (active.id === "sessions") void renderSessions();
    if (active.id === "system") void renderSystem();
  });
}
addEventListener("scroll", queueSectionUpdate, { passive: true });
addEventListener("resize", queueSectionUpdate);
queueSectionUpdate();

// ---- dialogue ------------------------------------------------------------
const turns = $<HTMLOListElement>("turns");
let pending: { el: HTMLElement; body: HTMLElement; text: string } | null = null;

function md(text: string): string {
  return DOMPurify.sanitize(marked.parse(text, { async: false }) as string, {
    FORBID_TAGS: ["style", "img", "svg", "math", "form", "input", "iframe"],
    ALLOWED_URI_REGEXP: /^(?:https?:|mailto:|#)/i,
  });
}

function addTurn(role: "user" | "jarvis", text: string, meta = ""): { el: HTMLElement; body: HTMLElement } {
  turns.querySelector(".empty")?.remove();
  const li = document.createElement("li");
  li.className = `turn ${role}`;
  const who = document.createElement("span");
  who.className = "turn-who";
  who.textContent = role === "user" ? "You" : "J.A.R.V.I.S";
  const body = document.createElement("div");
  body.className = "turn-body";
  if (role === "jarvis") body.innerHTML = md(text);
  else body.textContent = text;
  li.append(who, body);
  if (meta) {
    const m = document.createElement("span");
    m.className = "turn-meta";
    m.textContent = meta;
    li.append(m);
  }
  turns.append(li);
  li.scrollIntoView({ block: "end", behavior: "smooth" });
  return { el: li, body };
}

function streamToken(t: string): void {
  if (!pending) {
    const { el, body } = addTurn("jarvis", "");
    el.classList.add("pending");
    pending = { el, body, text: "" };
  }
  pending.text += t;
  pending.body.textContent = pending.text;
  pending.el.scrollIntoView({ block: "end" });
}

function finishAnswer(text: string, path: string, model?: string): void {
  const meta = [path === "deep" ? "full reasoning" : "voice path", model].filter(Boolean).join(" · ");
  if (pending) {
    pending.el.classList.remove("pending");
    pending.body.innerHTML = md(text || pending.text);
    const m = document.createElement("span");
    m.className = "turn-meta";
    m.textContent = meta;
    pending.el.append(m);
    pending = null;
  } else if (text) {
    addTurn("jarvis", text, meta);
  }
}

async function loadHistory(): Promise<void> {
  const requestedSession = session;
  turns.replaceChildren();
  pending = null;
  try {
    const msgs = await api.sessionTurns(requestedSession);
    if (requestedSession !== session) return;
    for (const m of msgs) {
      if (m.role === "user") addTurn("user", m.content);
      else if (m.role === "assistant") addTurn("jarvis", m.content);
    }
  } catch (e) {
    if (requestedSession !== session) return;
    if (!(e instanceof api.HttpError && e.status === 404)) whisper(String((e as Error).message), true);
  }
  if (!turns.children.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "A new conversation. Say something, or type below.";
    turns.append(li);
  }
}

function whisper(text: string, bad = false): void {
  const w = $("whisper");
  w.textContent = text;
  w.classList.toggle("bad", bad);
}

// ---- live events -----------------------------------------------------------
live
  .on("state", (s) => {
    $("stop").toggleAttribute("disabled", !["thinking", "transcribing", "speaking"].includes(s));
    field?.setState(s);
    if (!$("whisper").classList.contains("bad") || !["idle", "listening"].includes(s)) whisper(WHISPER[s] || s);
    $("core-title").textContent = TITLE[s] || s;
    document.querySelectorAll<HTMLLIElement>("#states li").forEach((li) =>
      li.setAttribute("data-active", String(li.dataset.state === PILL[s])),
    );
  })
  .on("link", (s) => {
    $("link-state").textContent = s === "open" ? "Link online" : s === "refused" ? "Link refused" : `Link ${s}`;
    $("link-led").className = `led ${s === "open" ? "on" : s === "refused" ? "bad" : ""}`;
    if (s === "refused") showGate("The hearth refused this token.");
  })
  .on("partial", (text) => {
    // Speculative: shown, not yet committed — the user may still be talking.
    const h = $("heard");
    h.textContent = text;
    h.classList.add("tentative");
  })
  .on("heard", (text) => {
    const h = $("heard");
    h.textContent = text;
    h.classList.remove("tentative");
    addTurn("user", text);
  })
  .on("retract", () => {
    // The user kept talking over an answer that had not been voiced yet. The
    // server cancelled it and will commit ONE merged question; drop both the
    // half-answer and the pre-merge question so the record matches what is saved.
    pending?.el.remove();
    pending = null;
    const users = turns.querySelectorAll(".turn.user");
    users[users.length - 1]?.remove();
    whisper("Still listening");
  })
  .on("token", streamToken)
  .on("answer", (text, path, model) => {
    finishAnswer(text, path, model);
    if (model) $("fact-brain").textContent = `${model} · ${path === "deep" ? "full reasoning" : "voice path"}`;
  })
  .on("log", (line) => whisper(line.replace(/^\s+/, "")))
  .on("error", (msg) => {
    whisper(msg, true);
    if (pending) {
      pending.el.classList.remove("pending");
      pending.el.classList.add("error");
      const detail = document.createElement("span");
      detail.className = "turn-meta";
      detail.textContent = msg;
      pending.el.append(detail);
      pending = null;
    } else addTurn("jarvis", msg, "Request status").el.classList.add("error");
  })
  .on("session", remember)
  .on("ready", (engine) => {
    engineInfo = engine;
    $("fact-ears").textContent = `Whisper ${engine.stt_model ?? "?"} · ${String(engine.stt ?? "?").toUpperCase()}`;
    $("fact-voice").textContent = `Kokoro ${engine.voice ?? "?"} · ${String(engine.tts ?? "?").toUpperCase()}`;
  });

let engineInfo: Record<string, unknown> = {};

// ---- controls ------------------------------------------------------------
async function setHandsFree(on: boolean): Promise<void> {
  try {
    await live.setHandsFree(on);
    handsFree = on;
  } catch (e) {
    handsFree = false;
    whisper(`Microphone unavailable: ${(e as Error).message}`, true);
  }
  for (const id of ["handsfree", "mic"]) $(id).setAttribute("aria-pressed", String(handsFree));
  $("handsfree").querySelector("b")!.textContent = handsFree ? "On" : "Off";
}

$("handsfree").addEventListener("click", () => void setHandsFree(!handsFree));
$("mic").addEventListener("click", () => void setHandsFree(!handsFree));
$("speak").addEventListener("click", () => {
  speak = !speak;
  live.setSpeak(speak);
  $("speak").setAttribute("aria-pressed", String(speak));
  $("speak").querySelector("b")!.textContent = speak ? "On" : "Off";
});
function renderFree(): void {
  for (const id of ["free", "free-alt"]) {
    $(id).setAttribute("aria-pressed", String(freeOnly));
    $(id).querySelector("b")!.textContent = freeOnly ? "On" : "Off";
  }
}
renderFree();
$("free-alt").addEventListener("click", () => $("free").click());
$("free").addEventListener("click", () => {
  freeOnly = !freeOnly;
  live.setFreeOnly(freeOnly);
  try {
    localStorage.setItem("jarvis.freeOnly", freeOnly ? "1" : "0");
  } catch {
    /* the toggle still applies to this tab */
  }
  renderFree();
  whisper(freeOnly ? "Free models only. Answers may be slower." : "Paid models first, free as fallback.");
});
$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $<HTMLInputElement>("prompt");
  const q = input.value.trim();
  if (!q) return;
  addTurn("user", q);
  $("heard").textContent = "";
  live.ask(q);
  input.value = "";
});
$("dialogue-toggle").addEventListener("click", toggleDialogue);
$("stop").addEventListener("click", () => live.interrupt());
$("new-session").addEventListener("click", () => {
  $("heard").textContent = "";
  whisper("Starting a new conversation");
  remember(api.newSessionId());
  live.setSession(session);
  void loadHistory();
});
let paused = false;
$("motion").addEventListener("click", () => {
  paused = !paused;
  field?.setPaused(paused);
  $("motion").setAttribute("aria-pressed", String(paused));
  $("motion").textContent = paused ? "Resume motion" : "Pause motion";
});
addEventListener("keydown", (e) => {
  const typing = (e.target as HTMLElement).matches("input, textarea");
  if (e.key === "Escape") live.interrupt();
  if (typing) return;
  if (e.key === " " || e.key.toLowerCase() === "h") {
    e.preventDefault();
    void setHandsFree(!handsFree);
  }
  if (e.key.toLowerCase() === "v") $("speak").click();
  if (e.key.toLowerCase() === "f") $("free").click();
  if (e.key.toLowerCase() === "d") toggleDialogue();
});

// ---- 02 sessions / 03 system -----------------------------------------------
const sessionsView = new SessionsView($("sessions"), () => session, sigil, async (id) => {
  remember(id);
  live.setSession(id);
  await loadHistory();
  $("core").scrollIntoView();
});
const systemView = new SystemView($("system"));

async function renderSessions(): Promise<void> { if (api.token()) await sessionsView.refresh(); }
async function renderSystem(): Promise<void> { if (api.token()) await systemView.refresh(); }
document.querySelector('a[data-act="sessions"]')!.addEventListener("click", () => void renderSessions());
document.querySelector('a[data-act="system"]')!.addEventListener("click", () => void renderSystem());
setInterval(() => {
  const rect = $("system").getBoundingClientRect();
  if (document.visibilityState === "visible" && rect.top < innerHeight && rect.bottom > 0) void renderSystem();
}, 15000);

// ---- arrival -----------------------------------------------------------------
function showGate(error = ""): void {
  document.body.classList.add("arriving");
  $("gate").classList.remove("gone");
  $("token-form").hidden = false;
  $("gate-error").textContent = error;
  $<HTMLInputElement>("token").focus();
}

async function enter(): Promise<void> {
  const typed = $<HTMLInputElement>("token").value.trim();
  if (typed) api.setToken(typed);
  if (!api.token()) {
    showGate("Paste the hearth token to connect.");
    return;
  }
  $("gate-error").textContent = "";
  try {
    await api.verify();
  } catch (e) {
    showGate((e as Error).message);
    return;
  }
  await live.unlockAudio().catch(() => undefined);
  field?.enter();
  $("gate").classList.add("gone");
  document.body.classList.remove("arriving");
  setTimeout(layout, 50);
  live.connect();
  await loadHistory();
  // A section deep link may have tried to load before the token was verified.
  for (const [id, refresh] of [["sessions", renderSessions], ["system", renderSystem]] as const) {
    const rect = $(id).getBoundingClientRect();
    if (rect.top < innerHeight && rect.bottom > 0) void refresh();
  }
}

document.body.classList.add("arriving");
if (!api.token()) $("token-form").hidden = false;
$("enter").addEventListener("click", () => void enter());
$("token-form").addEventListener("submit", (e) => {
  e.preventDefault();
  void enter();
});
