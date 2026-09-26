/** Transport only. No renderer or DOM dependency; the hearth remains authoritative. */
export type Turn = {
  role: string;
  content: string;
  ts?: string;
  telemetry?: Record<string, unknown>;
};
export type Session = {
  session_id: string;
  title: string;
  first_prompt?: string;
  latest_ts?: string;
  mtime: number;
  turn_count: number;
};
export type Model = {
  id?: string;
  model?: string;
  name?: string;
  label?: string;
  [key: string]: unknown;
};
export let token =
  sessionStorage.getItem("jarvis_hearth_token") ||
  localStorage.getItem("jarvis_hearth_token") ||
  "";
if (token) sessionStorage.setItem("jarvis_hearth_token", token);
localStorage.removeItem("jarvis_hearth_token");
export function setToken(value: string) {
  token = value;
  sessionStorage.setItem("jarvis_hearth_token", value);
}
export async function request(path: string, options: RequestInit = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...options.headers, Authorization: `Bearer ${token}` },
    signal: options.signal || AbortSignal.timeout(15000),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(
      response.status === 403
        ? "Connection token is missing or invalid. Reconnect in Settings."
        : data.error || `Request failed (${response.status})`,
    );
  }
  return response;
}
export async function json(path: string, options: RequestInit = {}) {
  return (await request(path, options)).json();
}
export async function ask(
  payload: object,
  onEvent: (event: string, data: any) => void,
  signal: AbortSignal,
) {
  const response = await request("/v1/ask", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.body) throw Error("Streaming is unavailable in this browser.");
  const reader = response.body.getReader(),
    decoder = new TextDecoder();
  let buffer = "",
    event = "message",
    data: string[] = [];
  const dispatch = () => {
    if (data.length) onEvent(event, JSON.parse(data.join("\n")));
    event = "message";
    data = [];
  };
  const line = (raw: string) => {
    const s = raw.replace(/\r$/, "");
    if (!s) {
      dispatch();
      return;
    }
    if (s.startsWith(":")) return;
    const p = s.indexOf(":");
    const key = p < 0 ? s : s.slice(0, p),
      value = p < 0 ? "" : s.slice(p + 1).replace(/^ /, "");
    if (key === "event") event = value;
    if (key === "data") data.push(value);
  };
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += done
        ? decoder.decode()
        : decoder.decode(value, { stream: true });
      let n;
      while ((n = buffer.indexOf("\n")) >= 0) {
        line(buffer.slice(0, n));
        buffer = buffer.slice(n + 1);
      }
      if (done) break;
    }
    if (buffer) line(buffer);
    dispatch();
  } finally {
    reader.releaseLock();
  }
}
