"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import "./flight.css";

/**
 * Speak a question (stage 2): the browser's Web Speech API turns speech into text that FILLS the composer. Nothing is
 * sent until the user presses send. Recognition runs in the browser (some browsers use their vendor's speech
 * service); FAULTLINE's API never receives audio. Where the API is missing the button is not rendered at all.
 */

interface SpeechAlternative {
  transcript: string;
}
interface SpeechResult {
  readonly length: number;
  readonly isFinal: boolean;
  [index: number]: SpeechAlternative;
}
interface SpeechResultList {
  readonly length: number;
  [index: number]: SpeechResult;
}
interface SpeechResultEvent {
  readonly resultIndex: number;
  readonly results: SpeechResultList;
}
interface SpeechErrorEvent {
  readonly error: string;
}
interface Recognizer {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((e: SpeechResultEvent) => void) | null;
  onerror: ((e: SpeechErrorEvent) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}
type RecognizerCtor = new () => Recognizer;

function recognizerCtor(): RecognizerCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecognizerCtor; webkitSpeechRecognition?: RecognizerCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const ERROR_TEXT: Record<string, string> = {
  "not-allowed": "Microphone access was blocked. Allow it in the browser to speak a question.",
  "service-not-allowed": "This browser does not allow speech recognition here.",
  "no-speech": "No speech heard. Press the mic and try again.",
  "audio-capture": "No microphone found.",
  network: "Speech recognition needs a network connection in this browser.",
};

function MicIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-[18px]" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5.5 11a6.5 6.5 0 0 0 13 0" />
      <path d="M12 17.5V21" />
    </svg>
  );
}

export function VoiceButton({ onTranscript, disabled }: { onTranscript: (text: string) => void; disabled: boolean }) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const recRef = useRef<Recognizer | null>(null);
  const onTextRef = useRef(onTranscript);

  useEffect(() => {
    onTextRef.current = onTranscript;
  }, [onTranscript]);

  // Detect support after mount only, so the static export renders the same markup on the server and the client.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- feature detection must run in the browser
    setSupported(recognizerCtor() !== null);
    return () => {
      recRef.current?.abort();
      recRef.current = null;
    };
  }, []);

  const stop = useCallback(() => {
    recRef.current?.stop();
  }, []);

  const start = useCallback(() => {
    const Ctor = recognizerCtor();
    if (!Ctor) return;
    recRef.current?.abort();
    const rec = new Ctor();
    rec.lang = (typeof navigator !== "undefined" && navigator.language) || "en-US";
    rec.continuous = false;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    rec.onresult = (e) => {
      let text = "";
      for (let i = 0; i < e.results.length; i += 1) text += e.results[i]?.[0]?.transcript ?? "";
      const t = text.trim();
      if (t) onTextRef.current(t);
    };
    rec.onerror = (e) => {
      if (e.error === "aborted") return;
      setStatus(ERROR_TEXT[e.error] ?? "Speech recognition stopped.");
    };
    rec.onend = () => {
      if (recRef.current === rec) recRef.current = null;
      setListening(false);
    };
    recRef.current = rec;
    setStatus(null);
    try {
      rec.start();
      setListening(true);
    } catch {
      recRef.current = null;
      setListening(false);
      setStatus("Speech recognition could not start.");
    }
  }, []);

  useEffect(() => {
    if (disabled && listening) recRef.current?.stop();
  }, [disabled, listening]);

  if (!supported) return null;

  return (
    <span className="flex min-w-0 items-center gap-2">
      <button
        type="button"
        onClick={listening ? stop : start}
        disabled={disabled && !listening}
        aria-pressed={listening}
        aria-label={listening ? "Stop listening" : "Speak a question"}
        title={listening ? "Stop listening" : "Speak a question (fills the box; nothing is sent until you press Ask)"}
        data-testid="chat-voice"
        data-listening={listening ? "true" : "false"}
        className={`relative flex size-11 shrink-0 items-center justify-center rounded-lg border transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-40 ${
          listening ? "border-fail bg-[color-mix(in_srgb,var(--fail)_12%,transparent)] text-fail" : "border-line-strong text-text-2 hover:bg-hover hover:text-text"
        }`}
      >
        {listening ? <span aria-hidden="true" className="voice-ring" /> : null}
        <MicIcon />
      </button>
      {listening || status ? (
        <span className="min-w-0 break-words font-mono text-[10.5px] text-muted" role="status" data-testid="chat-voice-status">
          {listening ? "Listening… speech fills the box; press Ask to send." : status}
        </span>
      ) : null}
    </span>
  );
}
