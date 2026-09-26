import { json } from "./api";
import type { CoreState } from "./scene";
export class LocalVoice {
  handsFree = false;
  recording = false;
  private generation = 0;
  private stream?: MediaStream;
  private context?: AudioContext;
  private processor?: ScriptProcessorNode;
  private source?: MediaStreamAudioSourceNode;
  private player?: HTMLAudioElement;
  private controller?: AbortController;
  private chunks: Float32Array[] = [];
  private rate = 48000;
  private started = 0;
  private lastSpeech = 0;
  private heard = false;
  constructor(
    private status: (text: string, state: CoreState) => void,
    private amplitude: (n: number) => void,
    private transcript: (text: string, send: boolean) => Promise<void>,
  ) {}
  async start(handsFree = false) {
    this.handsFree = handsFree;
    const generation = ++this.generation;
    try {
      const cap = await json("/v1/voice/capabilities");
      if (generation !== this.generation) return;
      if (!cap.transcription || !cap.synthesis)
        throw Error(
          "Install local voice with scripts/setup_voice.ps1. No online speech fallback is used.",
        );
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      if (generation !== this.generation) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      this.stream = stream;
      this.context = new AudioContext();
      this.rate = this.context.sampleRate;
      this.source = this.context.createMediaStreamSource(stream);
      this.processor = this.context.createScriptProcessor(4096, 1, 1);
      const silence = this.context.createGain();
      silence.gain.value = 0;
      this.source.connect(this.processor);
      this.processor.connect(silence);
      silence.connect(this.context.destination);
      this.chunks = [];
      this.started = performance.now();
      this.lastSpeech = this.started;
      this.heard = false;
      this.recording = true;
      this.status(
        handsFree
          ? "Hands-free · listening"
          : "Listening · click microphone to finish",
        "listening",
      );
      this.processor.onaudioprocess = (e) => {
        if (!this.recording) return;
        const input = new Float32Array(e.inputBuffer.getChannelData(0));
        this.chunks.push(input);
        let sum = 0;
        for (const v of input) sum += v * v;
        const rms = Math.sqrt(sum / input.length);
        this.amplitude(Math.min(1, rms * 8));
        const now = performance.now();
        if (rms > 0.016) {
          this.lastSpeech = now;
          this.heard = true;
        }
        if (
          now - this.started > 120000 ||
          (this.handsFree && this.heard && now - this.lastSpeech > 1300)
        )
          void this.finish();
        if (this.handsFree && !this.heard && now - this.started > 30000) {
          this.stop();
          this.status("Voice paused after 30 seconds of silence", "idle");
        }
      };
    } catch (e) {
      this.stop();
      this.status((e as Error).message, "idle");
    }
  }
  private release() {
    this.recording = false;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.processor?.disconnect();
    this.source?.disconnect();
    void this.context?.close();
    this.stream = undefined;
    this.context = undefined;
    this.amplitude(0);
  }
  async finish() {
    if (!this.recording) return;
    this.release();
    const generation = this.generation;
    this.status("Transcribing on this laptop…", "transcribing");
    const size = this.chunks.reduce((s, c) => s + c.length, 0),
      all = new Float32Array(size);
    let p = 0;
    for (const c of this.chunks) {
      all.set(c, p);
      p += c.length;
    }
    this.chunks = [];
    const length = Math.min(
        16000 * 120,
        Math.floor((size * 16000) / this.rate),
      ),
      buffer = new ArrayBuffer(44 + length * 2),
      view = new DataView(buffer);
    const word = (o: number, s: string) => {
      for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i));
    };
    word(0, "RIFF");
    view.setUint32(4, 36 + length * 2, true);
    word(8, "WAVEfmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, 16000, true);
    view.setUint32(28, 32000, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    word(36, "data");
    view.setUint32(40, length * 2, true);
    for (let i = 0; i < length; i++) {
      const from = (i * this.rate) / 16000;
      const k = Math.floor(from),
        f = from - k;
      const v = (all[k] || 0) * (1 - f) + (all[k + 1] || 0) * f;
      view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, v)) * 32767, true);
    }
    let binary = "";
    const bytes = new Uint8Array(buffer);
    for (let i = 0; i < bytes.length; i += 8192)
      binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    try {
      this.controller = new AbortController();
      const data = await json("/v1/voice/transcribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audio: btoa(binary) }),
        signal: AbortSignal.any([
          this.controller.signal,
          AbortSignal.timeout(190000),
        ]),
      });
      if (generation !== this.generation) return;
      if (!data.text.trim()) {
        this.stop();
        this.status("No speech recognized. Try again.", "idle");
        return;
      }
      await this.transcript(data.text, this.handsFree);
    } catch (e) {
      if (generation !== this.generation) return;
      this.stop();
      this.status((e as Error).message, "idle");
    }
  }
  async speak(text: string) {
    const generation = this.generation;
    try {
      const chunks =
        text.match(/[\s\S]{1,1600}(?:[.!?]\s|$)|[\s\S]{1,1600}/g) || [];
      for (const chunk of chunks) {
        if (generation !== this.generation) return;
        this.status("Preparing local voice…", "transcribing");
        this.controller = new AbortController();
        const data = await json("/v1/voice/synthesize", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: chunk }),
          signal: AbortSignal.any([
            this.controller.signal,
            AbortSignal.timeout(130000),
          ]),
        });
        if (generation !== this.generation) return;
        const bytes = Uint8Array.from(atob(data.audio), (c) => c.charCodeAt(0));
        const url = URL.createObjectURL(
          new Blob([bytes], { type: "audio/wav" }),
        );
        const player = (this.player = new Audio(url));
        const context = new AudioContext(),
          analyser = context.createAnalyser();
        context.createMediaElementSource(player).connect(analyser);
        analyser.connect(context.destination);
        analyser.fftSize = 256;
        const samples = new Uint8Array(analyser.frequencyBinCount);
        let raf = 0;
        const animate = () => {
          analyser.getByteFrequencyData(samples);
          this.amplitude(
            samples.reduce((a, b) => a + b, 0) / samples.length / 110,
          );
          raf = requestAnimationFrame(animate);
        };
        try {
          this.status("JARVIS is speaking · local voice", "speaking");
          animate();
          await new Promise<void>((resolve, reject) => {
            player.onended = () => resolve();
            player.onpause = () => resolve();
            player.onerror = () => reject(Error("Audio playback failed."));
            void player.play().catch(reject);
          });
        } finally {
          cancelAnimationFrame(raf);
          URL.revokeObjectURL(url);
          await context.close();
          this.amplitude(0);
        }
      }
      if (generation === this.generation) {
        this.status("Ready when you are", "idle");
        if (this.handsFree && !document.hidden) await this.start(true);
      }
    } catch (e) {
      if (generation === this.generation) {
        this.stop();
        this.status((e as Error).message, "idle");
      }
    }
  }
  stop() {
    this.generation++;
    this.handsFree = false;
    this.controller?.abort();
    this.player?.pause();
    this.release();
    this.chunks = [];
  }
}
