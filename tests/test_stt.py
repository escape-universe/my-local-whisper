"""wf/stt.py: die cuBLAS/cuDNN-DLL-Pruefung (ctypes, Lader austauschbar), die Rueckfall-Entscheidung
in _detect_device und der harte CUDA-Ladefehler-Rueckfall in Transcriber.load() (Arbeitspaket 4:
ein Rechner mit NVIDIA-Karte, aber ohne die Pip-Pakete aus requirements-gpu.txt, soll auf die CPU
ausweichen statt mit "Could not load library cudnn_ops...dll" abzustuerzen).

Kein echtes CUDA/Windows hier (CLAUDE.md: GPU laeuft in der Cloud nicht live) - Lader- und Modell-
Attrappen stehen fuer beides. sys.platform wird gezielt ueberschrieben (wie in tests/test_i18n.py
fuer ctypes.windll), damit die Windows-Zweige unabhaengig vom echten Testrechner pruefbar sind.

Seit Arbeitspaket 9: das Modell kommt zuerst nur aus dem lokalen Cache (local_files_only=True),
heruntergeladen wird nur, wenn es dort fehlt. Die faster_whisper-Attrappe spielt den Cache nach;
kein Test redet mit huggingface.co."""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

from wf import stt


# --- _ensure_cuda_dll_path(): fehlende nvidia-Pip-Pakete sind kein Fehler ------------------------
def _keine_echten_dll_verzeichnisse(monkeypatch) -> list:
    """Nachbesserung Arbeitspaket 9, Runde 1: auf einem Windows-Rechner mit den nvidia-Pip-Paketen
    liefe _ensure_cuda_dll_path() sonst wirklich - os.add_dll_directory und eine geaenderte PATH-
    Variable. Hier wird nur mitgeschrieben, PATH kommt nach dem Test zurueck."""
    aufrufe: list = []
    monkeypatch.setattr(stt.os, "add_dll_directory", aufrufe.append, raising=False)
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    return aufrufe


def test_ensure_cuda_dll_path_bleibt_still_wenn_nvidia_paket_fehlt(monkeypatch, capsys):
    """Nachbesserung Arbeitspaket 4, Runde 1 (Hinweis des Pruefers): systemweites CUDA/cuDNN statt
    der Pip-Wheels, oder requirements-gpu.txt einfach noch nicht installiert, ist der Normalfall -
    keine Fehlermeldung dafuer, auch nicht mitten in --doctor. "Paket fehlt" wird nachgestellt
    (find_spec meldet ein fehlendes Elternpaket "nvidia" mit ModuleNotFoundError), damit der Test
    auch auf einem Rechner mit den nvidia-Paketen genau diesen Fall prueft."""
    import importlib.util as importlib_util
    monkeypatch.setattr(stt.sys, "platform", "win32")
    dll_verzeichnisse = _keine_echten_dll_verzeichnisse(monkeypatch)

    def fehlt(pkg):
        raise ModuleNotFoundError(f"No module named {pkg.split('.')[0]!r}")

    monkeypatch.setattr(importlib_util, "find_spec", fehlt)
    stt._ensure_cuda_dll_path()
    assert capsys.readouterr().out == ""
    assert dll_verzeichnisse == []


def test_ensure_cuda_dll_path_meldet_einen_echten_fehler(monkeypatch, capsys):
    """Ein WIRKLICH unerwarteter Fehler (hier absichtlich provoziert, nicht "Paket fehlt") wird
    weiterhin gemeldet - nur ModuleNotFoundError (Paket fehlt einfach) ist still."""
    import importlib.util as importlib_util
    monkeypatch.setattr(stt.sys, "platform", "win32")
    dll_verzeichnisse = _keine_echten_dll_verzeichnisse(monkeypatch)

    def wirft(pkg):
        raise RuntimeError("Attrappe: unerwarteter Fehler")

    monkeypatch.setattr(importlib_util, "find_spec", wirft)
    stt._ensure_cuda_dll_path()
    assert "CUDA-DLL-Path-Setup failed" in capsys.readouterr().out
    assert dll_verzeichnisse == []


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
class LocalEntryNotFoundError(FileNotFoundError):
    """Gleichnamige Attrappe der huggingface_hub-Ausnahme "nicht im lokalen Cache" (dort seit 1.0
    FileNotFoundError + EntryNotFoundError, davor zusaetzlich HfHubHTTPError und ValueError)."""


class IncompleteSnapshotError(LocalEntryNotFoundError):
    """Attrappe der Unterklasse aus huggingface_hub >= 1.22.0: Snapshot nur halb heruntergeladen."""


def _fake_faster_whisper(monkeypatch, scheitert_bei: set[str], cache: str = "voll",
                         fehlt_als: type[Exception] = LocalEntryNotFoundError,
                         snapshot: Path | None = None) -> list[dict]:
    """WhisperModel(...) wirft, wenn device in scheitert_bei steht; sonst ein Dummy-Objekt
    (hf_tokenizer wird nicht gebraucht: initial_prompt ist in diesen Tests leer).

    Seit Arbeitspaket 9 auch der Modell-Cache wie in faster-whisper 1.2.1: ein vorhandener Ordner
    wird direkt gelesen; sonst entscheidet local_files_only (Standard False = Download, wie dort).
    cache "voll": liegt lokal. "leer": local_files_only=True wirft fehlt_als. "halb": abgebrochener
    Download unter huggingface_hub < 1.22.0 - der Ordner kommt zurueck, CTranslate2 scheitert an
    model.bin. Ein Download macht den Cache "voll", auch wenn danach das Geraet scheitert (erst
    Download, dann CTranslate2). snapshot: Ordner, den download_model(local_files_only=True)
    liefert (model.bin darin nur bei "voll"); ohne snapshot fehlt download_model in der Attrappe.
    Rueckgabe: alle WhisperModel-Aufrufe in Reihenfolge (Modell, Geraet, uebergebene Schalter)."""
    aufrufe: list[dict] = []
    zustand = {"cache": cache}
    modul = types.ModuleType("faster_whisper")

    class _Modell:
        def __init__(self, model_size, device, compute_type, **kwargs):
            aufrufe.append({"model": model_size, "device": device, **kwargs})
            if not os.path.isdir(model_size):
                if not kwargs.get("local_files_only", False):
                    zustand["cache"] = "voll"
                elif zustand["cache"] == "leer":
                    raise fehlt_als("Cannot find an appropriate cached snapshot folder (Attrappe)")
                elif zustand["cache"] == "halb":
                    raise RuntimeError("Unable to open file 'model.bin' in model (Attrappe)")
            if device in scheitert_bei:
                raise RuntimeError(f"Could not load library cudnn_ops...dll (Attrappe, device={device})")
            self.model_size, self.device, self.compute_type = model_size, device, compute_type

    def download_model(size_or_id, local_files_only=False, **kwargs):
        if local_files_only is not True:           # pytest.fail: kein Exception, geht durch jedes except
            pytest.fail("download_model ohne local_files_only=True waere ein Netzaufruf")
        if zustand["cache"] == "leer":
            raise fehlt_als("Cannot find an appropriate cached snapshot folder (Attrappe)")
        snapshot.mkdir(exist_ok=True)
        if zustand["cache"] == "voll":
            (snapshot / "model.bin").write_bytes(b"")
        return str(snapshot)

    modul.WhisperModel = _Modell
    if snapshot is not None:
        modul.download_model = download_model
    monkeypatch.setitem(sys.modules, "faster_whisper", modul)
    # device "cuda" ohne echte DLL-Pruefung (ctypes.WinDLL) und ohne os.add_dll_directory, auch auf
    # dem Windows-Runner und am Windows-Rechner: dort liefe sonst beides wirklich.
    monkeypatch.setattr(stt, "cuda_dlls_loadable", lambda loader=None: None)
    monkeypatch.setattr(stt, "_ensure_cuda_dll_path", lambda: None)
    return aufrufe


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


# --- Transcriber.load(): zuerst nur der lokale Cache, Download nur wenn noetig (Arbeitspaket 9) ---
def _schalter(aufrufe: list[dict]) -> list[tuple]:
    return [(a["device"], a.get("local_files_only")) for a in aufrufe]


def test_modell_im_cache_ein_einziger_lokaler_aufruf(monkeypatch, capsys):
    """Befund: ohne local_files_only fragte faster-whisper bei jedem Start huggingface.co.
    Liegt das Modell im Cache, gibt es genau einen Aufruf, und der bleibt lokal."""
    aufrufe = _fake_faster_whisper(monkeypatch, scheitert_bei=set())
    stt.Transcriber({"stt": {"device": "cpu"}}).load()
    assert aufrufe == [{"model": "large-v3-turbo", "device": "cpu", "local_files_only": True}]
    assert "downloading" not in capsys.readouterr().out


@pytest.mark.parametrize("fehlt_als", [LocalEntryNotFoundError, IncompleteSnapshotError])
def test_modell_fehlt_im_cache_einmal_herunterladen(monkeypatch, capsys, fehlt_als):
    """Erster Start oder anderes stt.model: erst lokal (scheitert mit der Cache-Ausnahme bzw. ihrer
    Unterklasse fuer einen halben Snapshot), dann genau einmal der Download, mit Konsolenzeile."""
    aufrufe = _fake_faster_whisper(monkeypatch, scheitert_bei=set(), cache="leer", fehlt_als=fehlt_als)
    t = stt.Transcriber({"stt": {"device": "cpu"}})
    t.load()
    assert _schalter(aufrufe) == [("cpu", True), ("cpu", False)]
    assert t._model is not None
    assert "downloading the speech model once" in capsys.readouterr().out


def test_nur_die_cache_ausnahme_loest_den_download_aus(monkeypatch):
    """Gezielt: ein anderer Fehler, auch einer mit derselben Basisklasse FileNotFoundError, wird
    weitergereicht - kein Download-Versuch."""
    class AndererFehler(FileNotFoundError):
        pass

    aufrufe = _fake_faster_whisper(monkeypatch, scheitert_bei=set(), cache="leer", fehlt_als=AndererFehler)
    with pytest.raises(AndererFehler):
        stt.Transcriber({"stt": {"device": "cpu"}}).load()
    assert _schalter(aufrufe) == [("cpu", True)]


def test_cuda_fehler_cpu_rueckfall_laedt_wieder_zuerst_lokal(monkeypatch, capsys, tmp_path):
    """CUDA scheitert beim lokalen Laden (Modell vollstaendig im Cache): der CPU-Rueckfall aus
    Arbeitspaket 4 greift wie bisher und laedt ebenfalls nur lokal - kein Download dazwischen."""
    aufrufe = _fake_faster_whisper(monkeypatch, scheitert_bei={"cuda"}, snapshot=tmp_path / "snap")
    t = stt.Transcriber({"stt": {"device": "cuda"}})
    t.load()
    assert _schalter(aufrufe) == [("cuda", True), ("cpu", True)]
    assert (t.device, t.compute_type) == ("cpu", "int8")
    out = capsys.readouterr().out
    assert "falling back to the CPU" in out and "downloading" not in out


def test_cache_fehlt_und_cuda_scheitert_ein_download_dann_cpu_lokal(monkeypatch):
    """Erster Start auf einem Rechner, dessen CUDA nicht laedt: einmal herunterladen (auf cuda
    versucht), dann laedt der CPU-Rueckfall das jetzt vorhandene Modell lokal."""
    aufrufe = _fake_faster_whisper(monkeypatch, scheitert_bei={"cuda"}, cache="leer")
    t = stt.Transcriber({"stt": {"device": "cuda"}})
    t.load()
    assert _schalter(aufrufe) == [("cuda", True), ("cuda", False), ("cpu", True)]
    assert t.device == "cpu"


def test_halber_snapshot_ohne_cache_ausnahme_wird_nachgeladen(monkeypatch, capsys, tmp_path):
    """Abgebrochener erster Download unter huggingface_hub < 1.22.0: der halbe Ordner kommt ohne
    Ausnahme zurueck, CTranslate2 scheitert an model.bin. Bisher lud der Hub-Abgleich den Rest
    nach; jetzt ebenso, einmal."""
    aufrufe = _fake_faster_whisper(monkeypatch, scheitert_bei=set(), cache="halb", snapshot=tmp_path / "snap")
    t = stt.Transcriber({"stt": {"device": "cpu"}})
    t.load()
    assert _schalter(aufrufe) == [("cpu", True), ("cpu", False)]
    assert "downloading the speech model once" in capsys.readouterr().out


def test_lokaler_modellordner_wie_bisher_ohne_download(monkeypatch, capsys, tmp_path):
    """stt.model als Pfad zu einem Modellordner: derselbe Aufruf wie vor Arbeitspaket 9 (ohne
    local_files_only), auch bei leerem Hub-Cache kein Download-Versuch."""
    aufrufe = _fake_faster_whisper(monkeypatch, scheitert_bei=set(), cache="leer")
    stt.Transcriber({"stt": {"device": "cpu", "model": str(tmp_path)}}).load()
    assert aufrufe == [{"model": str(tmp_path), "device": "cpu"}]
    assert "downloading" not in capsys.readouterr().out


def test_nicht_im_cache_erkennt_nur_die_cache_ausnahme():
    assert stt._nicht_im_cache(LocalEntryNotFoundError("x"))
    assert stt._nicht_im_cache(IncompleteSnapshotError("x"))
    assert not stt._nicht_im_cache(FileNotFoundError("model.bin"))
    assert not stt._nicht_im_cache(RuntimeError("CUDA failed with error out of memory"))
    assert not stt._nicht_im_cache(ValueError("Invalid model size 'large-v9'"))


def test_nicht_im_cache_mit_der_echten_ausnahme_von_huggingface_hub():
    """Mit der echten Klasse, wo huggingface_hub installiert ist (am Windows-Rechner mit
    requirements.txt; in CI und requirements-dev.txt fehlt es, dann uebersprungen). Ohne Netz."""
    hub_utils = pytest.importorskip("huggingface_hub.utils")
    assert stt._nicht_im_cache(hub_utils.LocalEntryNotFoundError("nicht im Cache"))
