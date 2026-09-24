"""wf/stt.py: die cuBLAS/cuDNN-DLL-Pruefung (ctypes, Lader austauschbar), die Rueckfall-Entscheidung
in _detect_device und der harte CUDA-Ladefehler-Rueckfall in Transcriber.load() (Arbeitspaket 4:
ein Rechner mit NVIDIA-Karte, aber ohne die Pip-Pakete aus requirements-gpu.txt, soll auf die CPU
ausweichen statt mit "Could not load library cudnn_ops...dll" abzustuerzen).

Kein echtes CUDA/Windows hier (CLAUDE.md: GPU laeuft in der Cloud nicht live) - Lader- und Modell-
Attrappen stehen fuer beides. sys.platform wird gezielt ueberschrieben (wie in tests/test_i18n.py
fuer ctypes.windll), damit die Windows-Zweige unabhaengig vom echten Testrechner pruefbar sind."""
from __future__ import annotations

import sys
import types

import pytest

from wf import stt


# --- _ensure_cuda_dll_path(): fehlende nvidia-Pip-Pakete sind kein Fehler ------------------------
def test_ensure_cuda_dll_path_bleibt_still_wenn_nvidia_paket_fehlt(monkeypatch, capsys):
    """Nachbesserung Arbeitspaket 4, Runde 1 (Hinweis des Pruefers): systemweites CUDA/cuDNN statt
    der Pip-Wheels, oder requirements-gpu.txt einfach noch nicht installiert, ist der Normalfall -
    keine Fehlermeldung dafuer, auch nicht mitten in --doctor."""
    monkeypatch.setattr(stt.sys, "platform", "win32")
    stt._ensure_cuda_dll_path()
    assert capsys.readouterr().out == ""


def test_ensure_cuda_dll_path_meldet_einen_echten_fehler(monkeypatch, capsys):
    """Ein WIRKLICH unerwarteter Fehler (hier absichtlich provoziert, nicht "Paket fehlt") wird
    weiterhin gemeldet - nur ModuleNotFoundError (Paket fehlt einfach) ist still."""
    import importlib.util as importlib_util
    monkeypatch.setattr(stt.sys, "platform", "win32")

    def wirft(pkg):
        raise RuntimeError("Attrappe: unerwarteter Fehler")

    monkeypatch.setattr(importlib_util, "find_spec", wirft)
    stt._ensure_cuda_dll_path()
    assert "CUDA-DLL-Path-Setup failed" in capsys.readouterr().out


# --- cuda_dlls_loadable(): Lader-Attrappe --------------------------------------------------------
def test_dll_pruefung_nicht_windows(monkeypatch):
    """None = nicht pruefbar -> der Lader wird gar nicht erst gerufen, kein Verhaltenswechsel."""
    monkeypatch.setattr(stt.sys, "platform", "linux")
    versucht = []
    assert stt.cuda_dlls_loadable(lambda name: versucht.append(name)) is None
    assert versucht == []


def test_dll_pruefung_alles_da(monkeypatch):
    monkeypatch.setattr(stt.sys, "platform", "win32")
    geladen = []

    def lader(name):
        geladen.append(name)
        return object()

    assert stt.cuda_dlls_loadable(lader) is True
    assert "cublas64_12.dll" in geladen


def test_dll_pruefung_cudnn_fehlt(monkeypatch):
    monkeypatch.setattr(stt.sys, "platform", "win32")

    def lader(name):
        if name.startswith("cudnn"):
            raise OSError("Modul nicht gefunden")
        return object()

    assert stt.cuda_dlls_loadable(lader) is False


def test_dll_pruefung_cublas_fehlt(monkeypatch):
    monkeypatch.setattr(stt.sys, "platform", "win32")

    def lader(name):
        if name.startswith("cublas"):
            raise OSError("Modul nicht gefunden")
        return object()

    assert stt.cuda_dlls_loadable(lader) is False


def test_dll_pruefung_akzeptiert_cudnn_generation_8(monkeypatch):
    """Kriterium: cuDNN 9 UND die aeltere Generation 8 (cudnn_ops_infer64_8.dll) werden akzeptiert."""
    monkeypatch.setattr(stt.sys, "platform", "win32")

    def lader(name):
        if name == "cudnn_ops64_9.dll":
            raise OSError("nur Generation 8 installiert")
        return object()

    assert stt.cuda_dlls_loadable(lader) is True


def test_dll_pruefung_nur_generation_9_reicht_auch(monkeypatch):
    monkeypatch.setattr(stt.sys, "platform", "win32")

    def lader(name):
        if name == "cudnn_ops_infer64_8.dll":
            raise OSError("nur Generation 9 installiert")
        return object()

    assert stt.cuda_dlls_loadable(lader) is True


# --- _detect_device(): Rueckfall-Entscheidung ----------------------------------------------------
def test_cpu_erzwungen_prueft_gar_nicht():
    aufgerufen = []
    assert stt._detect_device("cpu", dll_check=lambda: aufgerufen.append(1) or True) == ("cpu", "int8")
    assert aufgerufen == []


def test_cuda_erzwungen_warnt_nur_bei_fehlenden_dlls(capsys):
    """device: cuda ist ausdruecklich erzwungen -> nur warnen, nicht auf cpu umschalten."""
    assert stt._detect_device("cuda", dll_check=lambda: False) == ("cuda", "")
    out = capsys.readouterr().out
    assert "WARN" in out and stt.GPU_FIX_HINT in out


def test_cuda_erzwungen_ohne_warnung_wenn_dlls_da(capsys):
    assert stt._detect_device("cuda", dll_check=lambda: True) == ("cuda", "")
    assert capsys.readouterr().out == ""


def test_cuda_erzwungen_nicht_pruefbar_bleibt_still(capsys):
    """None (nicht pruefbar, z. B. kein Windows) aendert nichts - auch keine Warnung."""
    assert stt._detect_device("cuda", dll_check=lambda: None) == ("cuda", "")
    assert capsys.readouterr().out == ""


def _ctranslate2_attrappe(monkeypatch, anzahl: int) -> None:
    fake = types.ModuleType("ctranslate2")
    fake.get_cuda_device_count = lambda: anzahl
    monkeypatch.setitem(sys.modules, "ctranslate2", fake)


def test_auto_ohne_ctranslate2_gibt_cpu(monkeypatch):
    monkeypatch.delitem(sys.modules, "ctranslate2", raising=False)
    assert stt._detect_device("auto", dll_check=lambda: True) == ("cpu", "int8")


def test_auto_ohne_gpu_gibt_cpu(monkeypatch):
    _ctranslate2_attrappe(monkeypatch, 0)
    assert stt._detect_device("auto", dll_check=lambda: True) == ("cpu", "int8")


def test_auto_mit_gpu_und_dlls_gibt_cuda(monkeypatch):
    _ctranslate2_attrappe(monkeypatch, 1)
    assert stt._detect_device("auto", dll_check=lambda: True) == ("cuda", "")


def test_auto_mit_gpu_ohne_dlls_faellt_auf_cpu_zurueck(monkeypatch, capsys):
    """Das eigentliche Befund-Szenario (Arbeitspaket 4): NVIDIA-Karte gefunden, aber cuBLAS/cuDNN
    fehlen -> CPU statt eines Absturzes bei der ersten echten Rechnung, mit Abhilfe in der Konsole."""
    _ctranslate2_attrappe(monkeypatch, 1)
    assert stt._detect_device("auto", dll_check=lambda: False) == ("cpu", "int8")
    assert stt.GPU_FIX_HINT in capsys.readouterr().out


def test_auto_mit_gpu_nicht_pruefbar_bleibt_bei_cuda(monkeypatch):
    """None (z. B. kein Windows) aendert nichts am bisherigen Verhalten: GPU gefunden -> cuda."""
    _ctranslate2_attrappe(monkeypatch, 2)
    assert stt._detect_device("auto", dll_check=lambda: None) == ("cuda", "")


# --- Transcriber.load(): CUDA-Ladefehler faellt einmal auf die CPU zurueck ----------------------
def _fake_faster_whisper(monkeypatch, scheitert_bei: set[str]) -> None:
    """WhisperModel(...) wirft, wenn device in scheitert_bei steht; sonst ein Dummy-Objekt
    (hf_tokenizer wird nicht gebraucht: initial_prompt ist in diesen Tests leer)."""
    modul = types.ModuleType("faster_whisper")

    class _Modell:
        def __init__(self, model_size, device, compute_type):
            if device in scheitert_bei:
                raise RuntimeError(f"Could not load library cudnn_ops...dll (Attrappe, device={device})")
            self.model_size, self.device, self.compute_type = model_size, device, compute_type

    modul.WhisperModel = _Modell
    monkeypatch.setitem(sys.modules, "faster_whisper", modul)


def test_load_cuda_fehler_faellt_auf_cpu_zurueck(monkeypatch, capsys):
    _fake_faster_whisper(monkeypatch, scheitert_bei={"cuda"})
    t = stt.Transcriber({"stt": {"device": "cuda"}})
    assert t.device == "cuda"          # _detect_device liess "cuda" durch (auf Linux nicht pruefbar)
    t.load()
    assert (t.device, t.compute_type) == ("cpu", "int8")
    assert "falling back to the CPU" in capsys.readouterr().out


def test_load_cpu_fehler_wird_weitergereicht(monkeypatch):
    """Nur ein CUDA-Fehler wird abgefangen; scheitert schon die CPU, ist es ein echter Fehler."""
    _fake_faster_whisper(monkeypatch, scheitert_bei={"cpu"})
    t = stt.Transcriber({"stt": {"device": "cpu"}})
    with pytest.raises(RuntimeError):
        t.load()


def test_load_erfolgreiches_cuda_bleibt_cuda(monkeypatch):
    _fake_faster_whisper(monkeypatch, scheitert_bei=set())
    t = stt.Transcriber({"stt": {"device": "cuda"}})
    t.load()
    assert t.device == "cuda"
