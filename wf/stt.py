"""S2 — STT-Wrapper um faster-whisper (GPU). Default-Modell seit 05.09.2026: large-v3-turbo.

Modell wird EINMAL geladen und resident gehalten (kein Reload pro Diktat).
CUDA-DLL-Wiring nach Vorbild automations/slack-audio-transcribe/transcribe.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np


def _ensure_cuda_dll_path() -> None:
    """Windows laedt nvidia cublas/cudnn DLLs nicht aus site-packages — manuell adden.
    (uebernommen aus dem bewaehrten transcribe.py, R7 CUDA-Context).

    Fehlt das nvidia-Pip-Paket (oder ein Teil davon) einfach, ist das der Normalfall, kein Fehler:
    z. B. systemweites CUDA/cuDNN statt der Pip-Wheels, oder requirements-gpu.txt noch nicht
    installiert. find_spec() eines Untermoduls wirft dann ModuleNotFoundError (das Elternpaket
    "nvidia" fehlt) statt None zurueckzugeben - das wird deshalb still uebersprungen, nicht
    gemeldet. Nur ein WIRKLICH unerwarteter Fehler (z. B. keine Berechtigung fuer
    os.add_dll_directory) wird noch gedruckt (Hinweis des Pruefers, Nachbesserung Arbeitspaket 4,
    Runde 1: die Meldung kam bisher bei jedem Start mit device auto/cuda und ohne diese Pakete,
    auch waehrend --doctor)."""
    if sys.platform != "win32":
        return
    try:
        import importlib.util
        dirs: list[str] = []
        for pkg in ("nvidia.cublas", "nvidia.cudnn"):
            try:
                spec = importlib.util.find_spec(pkg)
            except ModuleNotFoundError:
                continue   # das nvidia-Paket ist schlicht nicht installiert
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


# cuBLAS 12 (Pip-Paket nvidia-cublas-cu12) und cuDNN, in zwei Generationen je nach installierter
# Version: 9.x seit CTranslate2 4.5 (Pip-Paket nvidia-cudnn-cu12>=9,<10), aeltere Installationen
# noch 8.x -> beide Namen akzeptieren (Befund Arbeitspaket 4, 24.09.2026).
_CUDA_DLLS: dict[str, tuple[str, ...]] = {
    "cublas": ("cublas64_12.dll",),
    "cudnn": ("cudnn_ops64_9.dll", "cudnn_ops_infer64_8.dll"),
}

GPU_FIX_HINT = "py -m pip install -r requirements-gpu.txt"


def cuda_dlls_loadable(loader: Callable[[str], object] | None = None) -> bool | None:
    """Sind cuBLAS UND cuDNN unter Windows ladbar? True/False, oder None = nicht pruefbar (kein
    Windows) -> das Ergebnis aendert dann nichts am Verhalten (Kriterium Arbeitspaket 4).

    ctypes mit winmode=0: das ist die Suchreihenfolge des NATIVEN DLL-Ladens inkl. PATH (seit
    Python 3.8 sucht ctypes sonst NICHT mehr automatisch in PATH) - damit prueft dies genau das,
    was CTranslate2 beim echten Laden ebenfalls vorfindet. loader ist austauschbar (Test/Monkeypatch),
    Default ctypes.WinDLL."""
    if sys.platform != "win32":
        return None
    _ensure_cuda_dll_path()  # Pip-Paket-bin-Ordner (falls installiert) in die Suche aufnehmen
    if loader is None:
        import ctypes

        def loader(name: str) -> object:
            return ctypes.WinDLL(name, winmode=0)
    for namen in _CUDA_DLLS.values():
        if not any(_dll_laedt(loader, n) for n in namen):
            return False
    return True


def _dll_laedt(loader: Callable[[str], object], name: str) -> bool:
    try:
        loader(name)
        return True
    except OSError:
        return False


def _detect_device(forced: str, dll_check: Callable[[], bool | None] | None = None) -> tuple[str, str]:
    """Returns (device, compute_type). dll_check prueft cuBLAS/cuDNN (Default: cuda_dlls_loadable),
    austauschbar fuer Tests. None (nicht pruefbar) aendert nichts am Verhalten."""
    check = dll_check or cuda_dlls_loadable
    if forced == "cpu":
        return "cpu", "int8"
    if forced == "cuda":
        # Ausdruecklich erzwungen: nur warnen, nicht umschalten (Kriterium Arbeitspaket 4).
        if check() is False:
            print(f"[stt] WARN: device is forced to \"cuda\", but cuBLAS/cuDNN could not be "
                  f"loaded -> the model load below may fail. Fix: {GPU_FIX_HINT}")
        return "cuda", ""  # compute_type kommt aus Config
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            if check() is False:
                print(f"[stt] CUDA GPU found, but cuBLAS/cuDNN could not be loaded -> using the "
                      f"CPU instead. Fix: {GPU_FIX_HINT}")
                return "cpu", "int8"
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
        try:
            self._model = WhisperModel(self.model_size, device=self.device,
                                       compute_type=self.compute_type)
        except Exception as e:  # noqa: BLE001
            # CUDA-Ladefehler (z. B. fehlende cuBLAS/cuDNN-DLL trotz device: cuda erzwungen, oder
            # eine GPU, die CTranslate2 doch nicht unterstuetzt) soll die App nicht abstuerzen
            # lassen: einmal auf CPU zurueckfallen (Kriterium Arbeitspaket 4). Scheitert das
            # ebenfalls, ist der Fehler echt und wird weitergereicht.
            if self.device != "cuda":
                raise
            print(f"[stt] CUDA model load failed ({e}) -> falling back to the CPU (compute=int8). "
                  f"Fix: {GPU_FIX_HINT}")
            self.device, self.compute_type = "cpu", "int8"
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
