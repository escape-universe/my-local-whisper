"""S1 — Mikrofon-Capture (sounddevice / WASAPI).

Nimmt auf, solange start()/stop() ein Fenster offen halten. Gibt float32-mono-Array
(16 kHz) direkt fuer faster-whisper zurueck — kein WAV-Roundtrip.

Seit 05.09.2026 (lange Reden): der Puffer kann WAEHREND der Aufnahme abschnittsweise geleert
werden (`drain_until_silence`), damit Whisper schon transkribiert, waehrend weitergesprochen wird.
Geschnitten wird nur in einer Sprechpause (Energie unter Schwelle fuer >= min_silence_s), damit
kein Wort in der Mitte zerfaellt.
"""
from __future__ import annotations

import threading
from typing import Any

import numpy as np
import sounddevice as sd


def list_devices() -> str:
    """Menschlich lesbare Geraeteliste (fuer --list-devices)."""
    return str(sd.query_devices())


def _resolve_device(device: Any) -> Any:
    """null -> Default; int -> Index; str -> erster Input mit Namens-Teilstring."""
    if device is None or device == "":
        return None
    if isinstance(device, int):
        return device
    name = str(device).lower()
    for idx, dev in enumerate(sd.query_devices()):
        if dev.get("max_input_channels", 0) > 0 and name in dev.get("name", "").lower():
            return idx
    return None  # nicht gefunden -> Default


def find_silence_cut(audio: np.ndarray, samplerate: int, min_silence_s: float = 0.45,
                     frame_ms: int = 20, rel_threshold: float = 0.12, abs_floor: float = 1e-3,
                     min_keep_s: float = 3.0) -> int | None:
    """Index (Samples) der LETZTEN Sprechpause im Array, an der man schneiden kann.
    Pause = zusammenhaengende Frames mit RMS < max(abs_floor, rel_threshold * Median-RMS der lauten Frames)
    ueber mindestens min_silence_s. Schnitt liegt in der Mitte der Pause. None wenn keine Pause
    gefunden oder der Schnitt naeher als min_keep_s am Anfang laege (zu kleiner Abschnitt)."""
    if audio is None or len(audio) < samplerate * (min_keep_s + min_silence_s):
        return None
    frame = max(1, samplerate * frame_ms // 1000)
    n = len(audio) // frame
    if n < 5:
        return None
    rms = np.sqrt(np.mean(audio[: n * frame].reshape(n, frame) ** 2, axis=1))
    # Schwelle relativ zum GRUNDRAUSCHEN, nicht zur Stille: Luefter/Rauschen liegen konstant ueber Null.
    # floor = leiseste 10 % der Frames (Rauschen), top = lauteste 10 % (Sprache); "Pause" = nah am floor.
    floor = float(np.percentile(rms, 5))
    top = float(np.percentile(rms, 90))
    if top < abs_floor * 3:
        return None  # praktisch Stille/nur ganz leises Rauschen: nichts Sinnvolles zu schneiden
    if top < floor * 1.5:
        # kaum Dynamik (durchgehend laut, z.B. Sprache ohne messbare Pausen oder reines Rauschen):
        # absolute Schwelle wie frueher; bei reinem Rauschen ergibt das keinen Schnitt
        thr = max(abs_floor, rel_threshold * top)
    else:
        thr = max(abs_floor, floor + rel_threshold * (top - floor))
    quiet = rms < thr
    need = max(1, int(round(min_silence_s * 1000 / frame_ms)))
    # von hinten nach vorn die letzte ausreichend lange Pause suchen
    run_end = None
    run_len = 0
    for i in range(n - 1, -1, -1):
        if quiet[i]:
            if run_end is None:
                run_end = i
            run_len += 1
            if run_len >= need:
                mid = (run_end + i) // 2
                cut = mid * frame
                if cut >= min_keep_s * samplerate:
                    return int(cut)
                return None
        else:
            run_end = None
            run_len = 0
    return None


class Recorder:
    """Push-to-talk-Recorder. start() oeffnet den Stream, stop() schliesst + liefert Audio.
    Waehrend der Aufnahme kann drain_until_silence() fertige Abschnitte abholen."""

    def __init__(self, samplerate: int = 16000, channels: int = 1,
                 device: Any = None, max_seconds: int = 3600):
        self.samplerate = samplerate
        self.channels = channels
        self.device = _resolve_device(device)
        self.max_frames = max_seconds * samplerate
        self._buf: list[np.ndarray] = []
        self._buf_lock = threading.Lock()
        # Schuetzt "Puffer entnehmen + Rest zurueckstellen" gegen ein gleichzeitiges stop():
        # sonst kann stop() einen leeren Puffer sehen, waehrend der Streamer gerade schneidet -> Audio weg.
        self._op_lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self._frames = 0            # insgesamt aufgenommen (fuer das Limit)
        self.limit_hit = False

    def _callback(self, indata, frames, time_info, status):  # noqa: ARG002
        # status kann Overflow melden; wir ignorieren es bewusst (Diktat, nicht Studio)
        if self._frames < self.max_frames:
            with self._buf_lock:
                self._buf.append(indata[:, 0].copy() if indata.ndim > 1 else indata.copy())
            self._frames += frames
        else:
            self.limit_hit = True

    def start(self) -> None:
        if self._stream is not None:
            return
        self._frames = 0
        self.limit_hit = False
        with self._buf_lock:
            self._buf.clear()
        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="float32",
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()

    def _take_all(self) -> np.ndarray:
        with self._buf_lock:
            chunks = self._buf
            self._buf = []
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks, axis=0).astype(np.float32)

    def buffered_seconds(self) -> float:
        """Sekunden im Puffer, die noch nicht abgeholt sind (wartet, falls gerade geschnitten wird)."""
        with self._op_lock:
            with self._buf_lock:
                return sum(len(c) for c in self._buf) / self.samplerate

    @property
    def elapsed_seconds(self) -> float:
        return self._frames / self.samplerate

    def drain_until_silence(self, min_seconds: float = 25.0, min_silence_s: float = 0.45,
                            max_chunk_s: float = 45.0) -> np.ndarray | None:
        """Liegt mehr als min_seconds im Puffer: bis zur letzten Sprechpause innerhalb der ersten
        max_chunk_s abholen, Rest bleibt. So bleiben Abschnitte auch dann klein, wenn der Puffer
        gross ist (Nachholen). None wenn zu wenig Audio oder keine Pause (dann spaeter erneut)."""
        if self.buffered_seconds() < min_seconds:
            return None
        with self._op_lock:
            if self._stream is None:
                return None  # schon gestoppt: stop() hat den Rest geholt
            audio = self._take_all()
            window = audio[: int(max_chunk_s * self.samplerate)]
            cut = find_silence_cut(window, self.samplerate, min_silence_s=min_silence_s)
            if cut is None and len(audio) > len(window):
                # in den ersten max_chunk_s keine Pause: im ganzen Puffer suchen (lieber ein langer Abschnitt als keiner)
                cut = find_silence_cut(audio, self.samplerate, min_silence_s=min_silence_s)
            if cut is None:
                # keine Pause: alles zurueck in den Puffer, spaeter nochmal
                with self._buf_lock:
                    self._buf.insert(0, audio)
                return None
            head, tail = audio[:cut], audio[cut:]
            with self._buf_lock:
                self._buf.insert(0, tail)
            return head

    def stop(self) -> np.ndarray:
        """Schliesst den Stream, gibt das (noch nicht abgeholte) float32-mono-Array zurueck."""
        if self._stream is None:
            return np.zeros(0, dtype=np.float32)
        with self._op_lock:
            self._stream.stop()
            self._stream.close()
            self._stream = None
            return self._take_all()

    @property
    def is_recording(self) -> bool:
        return self._stream is not None
