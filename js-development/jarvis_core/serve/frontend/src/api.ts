/**
 * Transport to the hearth. No DOM, no rendering — the hearth is the source of
 * truth for conversations; this file only reads it and carries the token.
 *
 * The token lives in sessionStorage only. A `?token=` in the URL is accepted
 * once, moved into sessionStorage and scrubbed from the address bar so it does
 * not sit in history or a screenshot.
 */

export type Turn = { role: string; content: string; ts?: string };
export type Session = {
  session_id: string;
  title: string;
  first_prompt?: string;
  latest_ts?: string;
  turn_count: number;
};
export type PipelineReport = {
  healthy: boolean | null;
  status?: string;
  generated_at?: string;
  breaches: Array<{ check: string; detail: string }>;
  backlog: Record<string, { pending: number; oldest: string; oldest_age_h?: number | null }>;
};
export type JobStatus = {
  name: string;
  paused?: boolean;
  status?: string;
  last_status?: string;
  consecutive_failures?: number;
  last_run_ts?: number | null;
  last_output?: string;
  [key: string]: unknown;
};
export type VoiceCapabilities = {
  warm: boolean;
  stt: string;
  tts: string;
  voice: string;
  stt_model: string;
  error: string | null;
};
export type Health = {
  ok: boolean;
  uptime_seconds: number;
  busy: boolean;
  requests_served: number;
  requests_rejected: number;
  last_error: string;
  warm?: { state: string; seconds: number | null; error: string | null };
  jobs?: JobStatus[];
  pipeline?: PipelineReport | null;
};

const TOKEN_KEY = "jarvis_hearth_token";

function adoptUrlToken(): void {
  const url = new URL(location.href);
  const t = url.searchParams.get("token");
  if (!t) return;
  sessionStorage.setItem(TOKEN_KEY, t);
  url.searchParams.delete("token");
  history.replaceState(null, "", url.pathname + (url.search ? url.search : "") + url.hash);
}
adoptUrlToken();
localStorage.removeItem(TOKEN_KEY);

export function token(): string {
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(value: string): void {
  sessionStorage.setItem(TOKEN_KEY, value.trim());
}

export class HttpError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { ...init.headers, Authorization: `Bearer ${token()}` },
    signal: init.signal || AbortSignal.timeout(15000),
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}) as Record<string, string>);
    throw new HttpError(
      r.status,
      r.status === 403 ? "The hearth refused this token." : body.error || `Request failed (${r.status})`,
    );
  }
  return (await r.json()) as T;
}

export const health = () => json<Health>("/v1/health");
export const voiceCapabilities = () => json<VoiceCapabilities>("/v1/voice/capabilities");
export const verify = () => json<{ ok: boolean }>("/v1/auth/verify");
export const sessions = () =>
  json<{ sessions: Session[] }>("/v1/sessions").then((d) =>
    [...d.sessions].sort((a, b) => (b.latest_ts || "").localeCompare(a.latest_ts || "")),
  );
export const sessionTurns = (id: string) =>
  json<{ messages: Turn[] }>(`/v1/sessions/${encodeURIComponent(id)}`).then((d) => d.messages);

export function liveUrl(): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/v1/voice/live?token=${encodeURIComponent(token())}`;
}

export function newSessionId(): string {
  return `conv-web-${crypto.randomUUID()}`;
}

export type Approval = { id: string; request_id: string; session: string; digest: string; tool: string;
  arguments: Record<string, unknown>; proposal: Record<string, unknown>; reason: string; expires_at: number; status: string };
export const approvals = (session: string) => json<{ approvals: Approval[]; requests: Array<{request_id: string; state: string; session: string}> }>(`/v1/approvals?session=${encodeURIComponent(session)}`);
export const decideApproval = (a: Approval, decision: "approve" | "deny") => json(`/v1/approvals/${encodeURIComponent(a.id)}`, {
  method: "POST", headers: {"Content-Type": "application/json"},
  body: JSON.stringify({request_id: a.request_id, session: a.session, digest: a.digest, decision}),
});
export const cancelRequest = (id: string, session: string) => json<{completed_actions?: Record<string, unknown>[]}>(`/v1/requests/${encodeURIComponent(id)}/cancel`, {
  method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({session}),
});
