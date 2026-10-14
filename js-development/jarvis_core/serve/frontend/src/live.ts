/**
 * The hands-free link: one WebSocket to WS /v1/voice/live for the whole
 * conversation. The browser only captures and plays audio — voice activity
 * detection, transcription, the brain and synthesis all run in the hearth, so
 * the server is the one place that knows whether JARVIS is listening,
 * thinking or speaking. This file mirrors that state; it never invents it.
 */
import { liveUrl, cancelRequest, Approval } from "./api";

export type CoreState = "waking" | "idle" | "listening" | "transcribing" | "thinking" | "speaking";
export type LiveState = CoreState | "awaiting_approval" | "stopping";

export type LiveEvents = {
  approval: (a: Approval | null) => void;
  terminated: (actions: Record<string, unknown>[]) => void;
  state: (s: LiveState) => void;
  link: (s: "connecting" | "open" | "closed" | "refused") => void;
  heard: (text: string) => void;
  partial: (text: string) => void;
  retract: () => void;
  token: (text: string) => void;
  answer: (text: string, path: string, model?: string) => void;
  log: (line: string) => void;
  error: (message: string) => void;
  session: (id: string) => void;
  ready: (engine: Record<string, unknown>) => void;
};

type Handlers = { [K in keyof LiveEvents]?: LiveEvents[K] };

export class Live {
  private ws: WebSocket | null = null;
  private handlers: Handlers = {};
  private retry = 0;
  private ctx: AudioContext | null = null;
  private mic: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private out: GainNode | null = null;
  private analyser: AnalyserNode | null = null;
  private playhead = 0;
  private sources = new Set<AudioBufferSourceNode>();
  private outRate = 24000;
  private wantHandsFree = false;
  private closedByUs = false;
  private acceptAudio = false;
  private requestId = "";
  private stopping: Promise<void> | null = null;
  private stopped: (() => void) | null = null;
  micLevel = 0;
  state: LiveState = "waking";

  constructor(private session: string, private speakReplies = true, private freeOnly = false) {}

  on<K extends keyof LiveEvents>(event: K, fn: LiveEvents[K]): this {
    this.handlers[event] = fn as never;
    return this;
  }

  /** Must be called from a user gesture: browsers refuse audio otherwise. */
  async unlockAudio(): Promise<void> {
    if (!this.ctx) {
      this.ctx = new AudioContext({ latencyHint: "interactive" });
      this.out = this.ctx.createGain();
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 512;
      this.out.connect(this.analyser);
      this.analyser.connect(this.ctx.destination);
    }
    if (this.ctx.state === "suspended") await this.ctx.resume();
  }

  connect(): void {
    this.closedByUs = false;
    this.handlers.link?.("connecting");
    const ws = new WebSocket(liveUrl());
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.handlers.link?.("open");
      this.send({ type: "hello", session: this.session, hands_free: this.wantHandsFree, speak: this.speakReplies,
                  free_only: this.freeOnly });
    };
    ws.onmessage = (m) => (typeof m.data === "string" ? this.onJson(m.data) : this.onAudio(m.data as ArrayBuffer));
    ws.onclose = (e) => {
      this.ws = null;
      if (e.code === 4403) {
        this.handlers.link?.("refused");
        return;
      }
      this.handlers.link?.("closed");
      if (!this.closedByUs) {
        const wait = Math.min(8000, 500 * 2 ** this.retry++);
        setTimeout(() => this.connect(), wait);
      }
    };
  }

  close(): void {
    this.closedByUs = true;
    this.ws?.close();
  }

  private send(obj: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj));
  }

  private onJson(raw: string): void {
    const ev = JSON.parse(raw);
    if (ev.session && ev.session !== this.session && ev.type !== "session") return;
    if (ev.type === "request") this.requestId = ev.request_id || "";
    if (ev.request_id && this.requestId && ev.request_id !== this.requestId) return;
    if (this.stopping && ["token", "answer", "audio_start"].includes(ev.type)) return;
    switch (ev.type) {
      case "approval":
        this.handlers.approval?.(ev as Approval);
        this.state = "awaiting_approval";
        this.handlers.state?.(this.state);
        break;
      case "approval_unavailable":
        this.handlers.error?.(`The proposed action cannot proceed: ${ev.reason}`);
        break;
      case "approval_resolved":
        this.handlers.approval?.(null);
        break;
      case "approval_expired":
        this.handlers.approval?.(null);
        this.handlers.error?.("Approval expired. The proposed action was not executed.");
        break;
      case "terminated":
        this.handlers.approval?.(null);
        this.handlers.terminated?.(ev.completed_actions ?? []);
        this.stopped?.();
        this.stopped = null;
        this.requestId = "";
        break;
      case "state":
        this.state = ev.state;
        this.handlers.state?.(ev.state);
        break;
      case "partial":
        this.handlers.partial?.(ev.text);
        break;
      case "final":
        this.handlers.heard?.(ev.text);
        break;
      case "retract":
        this.handlers.retract?.();
        break;
      case "cancelled":
        this.handlers.error?.("Reply stopped. You can ask another question.");
        break;
      case "stop_audio":
        this.flushPlayback();
        break;
      case "token":
        this.handlers.token?.(ev.text);
        break;
      case "answer":
        this.handlers.answer?.(ev.text || "", ev.path, ev.model);
        break;
      case "log":
        this.handlers.log?.(ev.line);
        break;
      case "error":
        this.handlers.error?.(ev.error);
        break;
      case "session":
        this.session = ev.session;
        this.handlers.session?.(ev.session);
        break;
      case "ready":
        this.handlers.ready?.(ev.engine || {});
        break;
      case "audio_start":
        this.acceptAudio = true;
        this.outRate = ev.rate || 24000;
        break;
    }
  }

  private onAudio(buf: ArrayBuffer): void {
    if (!this.acceptAudio || !this.ctx || !this.out) return;
    const pcm = new Int16Array(buf);
    const audio = this.ctx.createBuffer(1, pcm.length, this.outRate);
    const ch = audio.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768;
    const src = this.ctx.createBufferSource();
    src.buffer = audio;
    src.connect(this.out);
    // Chunks are scheduled back to back on the audio clock, so sentence N+1
    // starts exactly where N ends — no gap, no overlap.
    const start = Math.max(this.ctx.currentTime + 0.03, this.playhead);
    src.start(start);
    this.playhead = start + audio.duration;
    this.sources.add(src);
    src.onended = () => this.sources.delete(src);
  }

  /** The server heard the user speak over JARVIS: silence playback now. */
  private flushPlayback(): void {
    for (const s of this.sources) {
      try {
        s.stop();
      } catch {
        /* already ended */
      }
    }
    this.sources.clear();
    this.playhead = 0;
  }

  /** Stop JARVIS mid-sentence, locally at once and on the server. */
  interrupt(): Promise<void> {
    this.flushPlayback();
    this.acceptAudio = false;
    if (this.stopping) return this.stopping;
    const requestId = this.requestId;
    this.handlers.state?.("stopping");
    this.stopping = new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("The server has not confirmed execution cleanup")), 30000);
      this.stopped = () => { clearTimeout(timeout); resolve(); };
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.send({ type: "interrupt", cancel_turn: true, request_id: requestId });
      } else if (requestId) {
        void cancelRequest(requestId, this.session).then((result) => {
          clearTimeout(timeout);
          this.requestId = "";
          this.handlers.approval?.(null);
          this.handlers.terminated?.(result.completed_actions ?? []);
          this.handlers.state?.("idle");
          resolve();
        }).catch((e) => { clearTimeout(timeout); reject(e); });
      } else { clearTimeout(timeout); reject(new Error("Reconnect to terminate this request")); }
    }).catch((e) => { this.handlers.error?.(`Termination could not be confirmed: ${(e as Error).message}`); throw e; })
      .finally(() => { this.stopping = null; this.stopped = null; });
    return this.stopping;
  }

  ask(question: string): void {
    this.send({ type: "text", question });
  }

  setSpeak(on: boolean): void {
    this.speakReplies = on;
    this.send({ type: "config", speak: on });
    if (!on) {
      this.flushPlayback();
      this.send({ type: "interrupt", cancel_turn: false });
    }
  }

  /** Free models only: for when the paid balance is empty. */
  setFreeOnly(on: boolean): void {
    this.freeOnly = on;
    this.send({ type: "config", free_only: on });
  }

  async setSession(id: string): Promise<void> {
    if (this.requestId || ["transcribing", "thinking", "speaking", "awaiting_approval"].includes(this.state)) await this.interrupt();
    this.flushPlayback();
    this.acceptAudio = false;
    this.requestId = "";
    this.session = id;
    this.handlers.approval?.(null);
    this.send({ type: "config", session: id });
  }

  async setHandsFree(on: boolean): Promise<void> {
    this.wantHandsFree = on;
    if (on) await this.startMic();
    else this.stopMic();
    this.send({ type: "config", hands_free: on });
  }

  private async startMic(): Promise<void> {
    await this.unlockAudio();
    if (this.mic || !this.ctx) return;
    this.mic = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    await this.ctx.audioWorklet.addModule("/ui/mic-worklet.js");
    const source = this.ctx.createMediaStreamSource(this.mic);
    this.node = new AudioWorkletNode(this.ctx, "mic-downsampler");
    this.node.port.onmessage = (e) => {
      this.micLevel = e.data.rms;
      if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(e.data.pcm);
    };
    source.connect(this.node);
  }

  private stopMic(): void {
    this.node?.disconnect();
    this.node = null;
    this.mic?.getTracks().forEach((t) => t.stop());
    this.mic = null;
    this.micLevel = 0;
  }

  /** 0..1 loudness of what JARVIS is saying right now, for the core to pulse with. */
  voiceLevel(): number {
    if (!this.analyser) return 0;
    const data = new Uint8Array(this.analyser.fftSize);
    this.analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (const v of data) {
      const x = (v - 128) / 128;
      sum += x * x;
    }
    return Math.min(1, Math.sqrt(sum / data.length) * 4);
  }
}
