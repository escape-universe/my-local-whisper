"""S2 — STT-Wrapper um faster-whisper (GPU). Default-Modell seit 05.09.2026: large-v3-turbo.

Modell wird EINMAL geladen und resident gehalten (kein Reload pro Diktat).
CUDA-DLL-Wiring nach Vorbild automations/slack-audio-transcribe/transcribe.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import numpy as np


def _ensure_cuda_dll_path() -> None:
    """Windows laedt nvidia cublas/cudnn DLLs nicht aus site-packages — manuell adden.
    (uebernommen aus dem bewaehrten transcribe.py, R7 CUDA-Context)."""
    if sys.platform != "win32":
        return
    try:
        import importlib.util
        dirs: list[str] = []
        for pkg in ("nvidia.cublas", "nvidia.cudnn"):
            spec = importlib.util.find_spec(pkg)
            if not spec or not spec.submodule_search_locations:
                continue
            bin_dir = Path(spec.submodule_search_locations[0]) / "bin"
            if bin_dir.is_dir():
                dirs.append(str(bin_dir))
                os.add_dll_directory(str(bin_dir))
        if dirs:
            os.environ["PATH"] = os.pathsep.join(dirs + [os.environ.get("PATH", "")])
    except Exception as e:  # noqa: BLE001
        print(f"[stt] CUDA-DLL-Path-Setup failed: {e}")


def _detect_device(forced: str) -> tuple[str, str]:
    """Returns (device, compute_type)."""
    if forced == "cpu":
        return "cpu", "int8"
    if forced == "cuda":
        return "cuda", ""  # compute_type kommt aus Config
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", ""
    except Exception:  # noqa: BLE001
        pass
    return "cpu", "int8"


class Transcriber:
    def __init__(self, cfg: dict[str, Any], initial_prompt: str = ""):
        stt = cfg.get("stt", {})
        self.model_size = stt.get("model", "large-v3-turbo")
        forced = stt.get("device", "auto")
        self.device, cpu_ctype = _detect_device(forced)
        self.compute_type = cpu_ctype or stt.get("compute_type", "int8_float16")
        self.language = stt.get("language")  # None = auto
        self.beam_size = int(stt.get("beam_size", 5))
        # Diktat braucht keine Zeitstempel: spart Decoder-Schritte bei identischem Text (gemessen 05.09.2026).
        self.without_timestamps = bool(stt.get("without_timestamps", True))
        self.condition_on_previous_text = bool(stt.get("condition_on_previous_text", False))
        self.initial_prompt = initial_prompt or None
        self._model = None

    # Whisper haengt den initial_prompt VOR das Audio; mehr als ~224 Tokens werden vorne abgeschnitten
    # (also die ERSTEN Begriffe fallen weg). Wir kuerzen deshalb selbst von hinten (Liste = Prioritaet).
    PROMPT_TOKEN_BUDGET = 216
    # Nach der Begriffsliste ein neutraler Satz: Beginnt das Diktat mit genau den Namen, die am Ende des
    # Prompts stehen, laesst Whisper sie sonst weg (gemessen 05.09.2026 in der Kalibrierung: "Paperless, Max,
    # Zigbee, Matrix, Besprechungsraum" -> nur "Besprechungsraum, Konferenzraum."; mit diesem Schluss vollstaendig).
    PROMPT_SUFFIX = " Das Diktat beginnt jetzt."

    def load(self) -> None:
        if self._model is not None:
            return
        if self.device == "cuda":
            _ensure_cuda_dll_path()
        from faster_whisper import WhisperModel
        print(f"[stt] loading {self.model_size} on {self.device} (compute={self.compute_type}) ...")
        self._model = WhisperModel(self.model_size, device=self.device,
                                   compute_type=self.compute_type)
        self._fit_prompt()

    def _fit_prompt(self) -> None:
        """initial_prompt auf das Token-Budget kuerzen (Begriffe von hinten weglassen)."""
        if not self.initial_prompt:
            return
        if self.initial_prompt.endswith(self.PROMPT_SUFFIX):
            return
        try:
            from faster_whisper.tokenizer import Tokenizer
            tok = Tokenizer(self._model.hf_tokenizer, True, task="transcribe", language="de")
            n = len(tok.encode(self.initial_prompt))
            if n <= self.PROMPT_TOKEN_BUDGET:
                self.initial_prompt += self.PROMPT_SUFFIX
                print(f"[stt] initial_prompt: {n} tokens + closing sentence (budget {self.PROMPT_TOKEN_BUDGET})")
                return
            head, _, body = self.initial_prompt.partition(":")
            terms = [t.strip().rstrip(".") for t in body.split(",") if t.strip()]
            dropped = 0
            while terms and len(tok.encode(head + ": " + ", ".join(terms) + ".")) > self.PROMPT_TOKEN_BUDGET:
                terms.pop()
                dropped += 1
            self.initial_prompt = head + ": " + ", ".join(terms) + "." + self.PROMPT_SUFFIX
            print(f"[stt] initial_prompt was {n} tokens -> dropped the last {dropped} terms "
                  f"(Budget {self.PROMPT_TOKEN_BUDGET}); shorten or reorder dictionary.txt.")
        except Exception as e:  # noqa: BLE001
            print(f"[stt] prompt trimming skipped: {e}")

    def warmup(self) -> None:
        """Dummy-Inferenz, damit das erste echte Diktat kein Cold-Start-Clipping hat (R6)."""
        self.load()
        silence = np.zeros(self.samplerate_hint, dtype=np.float32)
        try:
            list(self._model.transcribe(silence, language="de", beam_size=1)[0])
        except Exception as e:  # noqa: BLE001
            print(f"[stt] warmup soft-fail: {e}")

    samplerate_hint = 16000

    def transcribe(self, audio: np.ndarray) -> dict[str, Any]:
        """float32-mono-16kHz-Array -> {text, language, duration}."""
        self.load()
        if audio is None or len(audio) < self.samplerate_hint // 4:  # < 0.25 s
            return {"text": "", "language": self.language or "de", "duration": 0.0}
        segments_iter, info = self._model.transcribe(
            audio,
            language=self.language,
            beam_size=self.beam_size,
            vad_filter=True,   # Silero VAD integriert (F2 — kein separates webrtcvad)
            initial_prompt=self.initial_prompt,
            without_timestamps=self.without_timestamps,
            condition_on_previous_text=self.condition_on_previous_text,
        )
        parts = [seg.text for seg in segments_iter]
        text = " ".join(p.strip() for p in parts).strip()
        return {
            "text": text,
            "language": getattr(info, "language", self.language or "de"),
            "duration": getattr(info, "duration", 0.0),
        }
