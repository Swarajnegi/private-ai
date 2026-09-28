// Microphone -> 16 kHz PCM16 frames of 512 samples (32 ms), the exact frame
// the hearth's Silero VAD consumes. Runs on the audio thread so capture never
// stutters when the page is busy rendering the core.
class MicDownsampler extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.pos = 0;            // fractional read position into the input stream
    this.prev = 0;           // last input sample, for interpolation across blocks
    this.frame = new Int16Array(512);
    this.fill = 0;
    this.sumSq = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    // Linear interpolation from the device rate down to 16 kHz.
    while (this.pos < ch.length) {
      const i = Math.floor(this.pos);
      const f = this.pos - i;
      const a = i === 0 ? this.prev : ch[i - 1];
      const b = ch[i];
      const s = a + (b - a) * f;
      const clipped = Math.max(-1, Math.min(1, s));
      this.frame[this.fill++] = clipped * 32767;
      this.sumSq += clipped * clipped;
      if (this.fill === 512) {
        const rms = Math.sqrt(this.sumSq / 512);
        this.port.postMessage({ pcm: this.frame.buffer, rms }, [this.frame.buffer]);
        this.frame = new Int16Array(512);
        this.fill = 0;
        this.sumSq = 0;
      }
      this.pos += this.ratio;
    }
    this.pos -= ch.length;
    this.prev = ch[ch.length - 1];
    return true;
  }
}

registerProcessor("mic-downsampler", MicDownsampler);
