/**
 * Procedural sound cues synthesized with the Web Audio API: no audio files, no dependencies.
 * Cues are off until the operator turns them on; that click is the user gesture browsers
 * require before an AudioContext may produce sound.
 */
export type Cue = "catastrophe" | "resolve";

const STORAGE_KEY = "faultline.sound";

export function readSoundPreference(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "on";
  } catch {
    return false;
  }
}

export function writeSoundPreference(on: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, on ? "on" : "off");
  } catch {}
}

let context: AudioContext | null = null;
/** Audio devices can take a moment to wake; a cue still waiting after this is dropped, not played late. */
const RESUME_GRACE_MS = 500;

function audio(): AudioContext | null {
  if (typeof window === "undefined" || typeof window.AudioContext !== "function") return null;
  // Before any user gesture the browser keeps a new context suspended; don't create one that cannot sound.
  if (!context && navigator.userActivation && !navigator.userActivation.hasBeenActive) return null;
  context ??= new window.AudioContext({ latencyHint: "interactive" });
  return context;
}

interface Voice {
  type: OscillatorType; frequency: number; glideTo?: number; start: number; duration: number; peak: number;
}

/** One oscillator with a fast attack and an exponential decay, so it never clicks. */
function voice(ctx: AudioContext, destination: AudioNode, v: Voice): void {
  const oscillator = ctx.createOscillator();
  const envelope = ctx.createGain();
  oscillator.type = v.type;
  oscillator.frequency.setValueAtTime(v.frequency, v.start);
  if (v.glideTo) oscillator.frequency.exponentialRampToValueAtTime(v.glideTo, v.start + v.duration);
  envelope.gain.setValueAtTime(0.0001, v.start);
  envelope.gain.exponentialRampToValueAtTime(v.peak, v.start + 0.012);
  envelope.gain.exponentialRampToValueAtTime(0.0001, v.start + v.duration);
  oscillator.connect(envelope).connect(destination);
  oscillator.start(v.start);
  oscillator.stop(v.start + v.duration + 0.05);
}

export function playCue(cue: Cue): void {
  const ctx = audio();
  if (!ctx) return;
  if (ctx.state === "running") return schedule(ctx, cue);
  // A suspended (or, on iOS, interrupted) context would hold the cue until the next click and
  // sound it then, out of step with the event. Play it only if the context resumes promptly.
  const asked = performance.now();
  ctx.resume().then(() => {
    if (performance.now() - asked <= RESUME_GRACE_MS) schedule(ctx, cue);
  }, () => {});
}

function schedule(ctx: AudioContext, cue: Cue): void {
  const t = ctx.currentTime + 0.02;
  const master = ctx.createGain();
  master.gain.value = 0.16;
  master.connect(ctx.destination);

  if (cue === "catastrophe") {
    // Two hits of a detuned saw pair falling a tritone through a closing low-pass: plainly wrong, never shrill.
    const filter = ctx.createBiquadFilter();
    filter.type = "lowpass";
    filter.Q.value = 6;
    filter.frequency.setValueAtTime(2600, t);
    filter.frequency.exponentialRampToValueAtTime(260, t + 0.9);
    filter.connect(master);
    for (const [offset, duration] of [[0, 0.22], [0.26, 0.72]] as const) {
      for (const detune of [-4, 4]) {
        voice(ctx, filter, { type: "sawtooth", frequency: 233.08 + detune, glideTo: 164.81, start: t + offset, duration, peak: 0.42 });
      }
      voice(ctx, filter, { type: "square", frequency: 116.54, glideTo: 82.41, start: t + offset, duration, peak: 0.2 });
    }
    return;
  }

  // A major triad arpeggiated up to the octave: the failure resolved into a verified pass.
  const notes = [523.25, 659.25, 783.99, 1046.5];
  notes.forEach((frequency, i) => {
    voice(ctx, master, { type: i === notes.length - 1 ? "sine" : "triangle", frequency, start: t + i * 0.085, duration: 1.2 - i * 0.12, peak: 0.3 });
  });
}
