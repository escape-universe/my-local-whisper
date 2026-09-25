"""wf/doctor.py: `py whisperflow.py --doctor` prueft die Einrichtung und druckt je Pruefpunkt eine
[OK]/[WARN]/[FAIL]-Zeile. Kein echtes Netzwerk (die conftest sperrt es); die Pruefpunkte mit
Netzwerkbedarf (Ollama) werden ueber Cleaner.diagnose() per monkeypatch gefuettert, wie in
tests/test_cleanup.py. Muss auch auf diesem (Linux-)Testrechner ohne Windows/GPU/Mikrofon
durchlaufen, ohne abzustuerzen (Arbeitspaket 4, Kriterium 5).

Nachbesserung Runde 1 (Bloecker B1/B2 des Pruefers): wf/doctor.py importiert am eigenen Kopf nur
die Standardbibliothek (wf.cleanup/config/stt kommen erst innerhalb der jeweiligen Pruefung) -
"cleanup"/"stt" tauchen deshalb hier nicht mehr als Modulattribute von doctor auf, sondern werden
direkt aus wf importiert und dort gepatcht. Ausserdem ein Subprozess-Test (test_doctor_subprozess_*),
der echte fehlende Kernpakete simuliert - genau der Fall, den die conftest-Attrappen verdecken.

Nachbesserung Arbeitspaket 9, Runde 1: Pruefzeile "speech model cache" (liegt das Whisper-Modell
lokal, mit tokenizer.json?), mit einer faster_whisper-Attrappe und ohne Netz."""
from __future__ import annotations

import subprocess
import sys
import textwrap
import types

import pytest

from wf import cleanup, doctor
from wf import config as config_mod
from wf import stt


# --- Python/Betriebssystem -----------------------------------------------------------------------
def test_python_version_ok_ab_3_11(monkeypatch):
    monkeypatch.setattr(doctor.sys, "version_info", (3, 11, 0))
    status, text = doctor._check_python()
    assert status == "ok" and "3.11.0" in text


def test_python_version_zu_alt_ist_fail(monkeypatch):
    monkeypatch.setattr(doctor.sys, "version_info", (3, 10, 9))
    status, text = doctor._check_python()
    assert status == "fail" and "3.10.9" in text


def test_os_windows_ist_ok_sonst_warn(monkeypatch):
    monkeypatch.setattr(doctor.sys, "platform", "win32")
    assert doctor._check_os() == ("ok", "Windows")
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    status, text = doctor._check_os()
    assert status == "warn" and "Windows" in text


# --- importierbare Pakete -------------------------------------------------------------------------
def test_check_import_vorhandenes_paket_ist_ok():
    assert doctor._check_import("json", "json", False) == ("ok", "json importable")


def test_check_import_fehlendes_paket_ist_fail_mit_abhilfe():
    status, text = doctor._check_import("gibt_es_nicht_4711", "irgendwas", False)
    assert status == "fail" and "py -m pip install irgendwas" in text


def test_check_import_optionales_paket_ist_nur_warn():
    status, _ = doctor._check_import("gibt_es_nicht_4711", "irgendwas", True)
    assert status == "warn"


def test_check_import_sounddevice_prueft_portaudio_mit(monkeypatch):
    """Der Import kann klappen, auch wenn PortAudio selbst fehlt - das schlaegt erst beim
    Aufruf fehl, hier durch eine Attrappe simuliert."""
    fake = types.ModuleType("sounddevice")

    def kaputt(*a, **kw):
        raise OSError("PortAudio library not found")

    fake.query_devices = kaputt
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    status, text = doctor._check_import("sounddevice", "sounddevice", False)
    assert status == "fail" and "PortAudio" in text


# --- config.yaml -----------------------------------------------------------------------------------
def test_check_config_liest_die_ausgelieferte_config_yaml():
    status, text, cfg = doctor._check_config()
    assert status == "ok" and cfg is not None and "llm" in cfg


def test_check_config_ohne_pyyaml_nennt_das_paket_nicht_die_datei(monkeypatch):
    """Nachbesserung Arbeitspaket 4, Runde 2 (Hinweis des Pruefers): im leeren venv hiess die
    Zeile "config.yaml unreadable (No module named 'yaml')" - die Datei ist aber lesbar, es fehlt
    nur PyYAML (die eigene [FAIL]-Zeile fuer "yaml" in _PACKAGES sagt das schon)."""
    import builtins
    monkeypatch.delitem(sys.modules, "yaml", raising=False)
    echter_import = builtins.__import__

    def kein_yaml(name, *a, **kw):
        if name == "yaml":
            raise ModuleNotFoundError("No module named 'yaml'")
        return echter_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", kein_yaml)
    status, text, cfg = doctor._check_config()
    assert status == "fail" and cfg is None
    assert "PyYAML" in text and "unreadable" not in text


# --- Mikrofon --------------------------------------------------------------------------------------
def _mit_geraeten(monkeypatch, geraete: list[dict]) -> None:
    """query_devices() auf dem BESTEHENDEN sounddevice-Modul-Objekt austauschen, nicht per
    sys.modules ersetzen: wf/audio.py hat beim eigenen Import (durch andere Tests/Module, die es
    schon vorher laden) eine eigene Referenz auf denselben Namen gebunden (`import sounddevice as
    sd`) - ein Ersetzen des sys.modules-Eintrags erreicht diese bestehende Referenz nicht mehr,
    _resolve_device() saehe dann weiter die alte (leere) Attrappe."""
    import sounddevice as sd
    monkeypatch.setattr(sd, "query_devices", lambda *a, **kw: geraete)


def test_mikrofon_ohne_sounddevice_ist_warn(monkeypatch):
    monkeypatch.delitem(sys.modules, "sounddevice", raising=False)
    status, text = doctor._check_microphone({"audio": {}})
    assert status == "warn" and "cannot check" in text


def test_mikrofon_kein_geraet_ist_fail(monkeypatch):
    _mit_geraeten(monkeypatch, [])
    status, text = doctor._check_microphone({"audio": {}})
    assert status == "fail" and "no input device" in text


def test_mikrofon_standardgeraet_ok(monkeypatch):
    _mit_geraeten(monkeypatch, [{"name": "Mic A", "max_input_channels": 2}])
    status, text = doctor._check_microphone({"audio": {"input_device": None}})
    assert status == "ok" and "1 input device" in text


def test_mikrofon_konfiguriert_per_name_gefunden(monkeypatch):
    _mit_geraeten(monkeypatch, [{"name": "USB Mic", "max_input_channels": 1}])
    status, text = doctor._check_microphone({"audio": {"input_device": "usb"}})
    assert status == "ok" and "USB Mic" in text


def test_mikrofon_konfiguriert_per_index_gefunden(monkeypatch):
    _mit_geraeten(monkeypatch, [{"name": "Mic A", "max_input_channels": 1},
                                {"name": "Mic B", "max_input_channels": 1}])
    status, text = doctor._check_microphone({"audio": {"input_device": 1}})
    assert status == "ok" and "Mic B" in text


def test_mikrofon_konfiguriert_nicht_gefunden_ist_fail(monkeypatch):
    _mit_geraeten(monkeypatch, [{"name": "USB Mic", "max_input_channels": 1}])
    status, text = doctor._check_microphone({"audio": {"input_device": "nirwana"}})
    assert status == "fail" and "nirwana" in text


def test_mikrofon_konfigurierter_index_ausser_bereich_ist_fail(monkeypatch):
    """Nachbesserung Arbeitspaket 4, Runde 1 (B2): eine veraltete Geraete-Nummer (z. B. nach dem
    Abstecken eines USB-Mikrofons, die Nummern verschieben sich dann) darf --doctor nicht mit
    einem IndexError abschiessen - wf/audio._resolve_device(int) gibt eine Zahl UNGEPRUEFT
    zurueck, das muss _check_microphone selbst gegen die aktuelle Geraeteliste abfangen."""
    _mit_geraeten(monkeypatch, [{"name": "Mic A", "max_input_channels": 1}])
    status, text = doctor._check_microphone({"audio": {"input_device": 7}})
    assert status == "fail" and "--list-devices" in text


def test_mikrofon_konfigurierter_index_ohne_eingang_ist_fail(monkeypatch):
    """Ein gueltiger Index, der aber kein Eingabegeraet ist (max_input_channels 0), ist ebenso
    falsch konfiguriert wie eine Nummer, die es gar nicht gibt. Ein ECHTES Eingabegeraet muss
    dabei sein (Index 0), sonst greift schon die vorherige "kein Mikrofon"-Pruefung."""
    _mit_geraeten(monkeypatch, [{"name": "Mic A", "max_input_channels": 1},
                                {"name": "Lautsprecher", "max_input_channels": 0}])
    status, text = doctor._check_microphone({"audio": {"input_device": 1}})
    assert status == "fail" and "--list-devices" in text


# --- GPU -------------------------------------------------------------------------------------------
def _ctranslate2_attrappe(monkeypatch, anzahl: int) -> None:
    fake = types.ModuleType("ctranslate2")
    fake.get_cuda_device_count = lambda: anzahl
    monkeypatch.setitem(sys.modules, "ctranslate2", fake)


def test_gpu_ohne_ctranslate2_ist_warn(monkeypatch):
    monkeypatch.delitem(sys.modules, "ctranslate2", raising=False)
    status, text = doctor._check_gpu()
    assert status == "warn" and "ctranslate2" in text


def test_gpu_ohne_karte_ist_warn(monkeypatch):
    _ctranslate2_attrappe(monkeypatch, 0)
    status, text = doctor._check_gpu()
    assert status == "warn" and "no CUDA GPU" in text


def test_gpu_mit_karte_und_dlls_ist_ok(monkeypatch):
    _ctranslate2_attrappe(monkeypatch, 1)
    monkeypatch.setattr(stt, "cuda_dlls_loadable", lambda: True)
    status, text = doctor._check_gpu()
    assert status == "ok" and "1 CUDA GPU" in text


def test_gpu_mit_karte_ohne_dlls_ist_warn_mit_abhilfe(monkeypatch):
    """Das Befund-Szenario: NVIDIA-Karte da, cuBLAS/cuDNN fehlen - die App faellt selbst auf die
    CPU zurueck (wf/stt.py), darum WARN statt FAIL."""
    _ctranslate2_attrappe(monkeypatch, 1)
    monkeypatch.setattr(stt, "cuda_dlls_loadable", lambda: False)
    status, text = doctor._check_gpu()
    assert status == "warn" and stt.GPU_FIX_HINT in text


def test_gpu_mit_karte_nicht_pruefbar_ist_ok(monkeypatch):
    """None (z. B. dieser Linux-Testrechner, dll-Pruefung ist Windows-spezifisch) -> keine
    falsche Behauptung, aber auch kein WARN fuer etwas, das gar nicht geprueft werden kann."""
    _ctranslate2_attrappe(monkeypatch, 2)
    monkeypatch.setattr(stt, "cuda_dlls_loadable", lambda: None)
    status, text = doctor._check_gpu()
    assert status == "ok" and "2 CUDA GPU" in text


# --- Sprachmodell im lokalen Cache (Nachbesserung Arbeitspaket 9, Runde 1) -------------------------
class LocalEntryNotFoundError(FileNotFoundError):
    """Gleichnamige Attrappe der huggingface_hub-Ausnahme "nicht im lokalen Cache"."""


def _faster_whisper_mit_snapshot(monkeypatch, snapshot, dateien=("model.bin", "tokenizer.json")) -> list:
    """faster_whisper-Attrappe: download_model(..., local_files_only=True) liefert den Snapshot-
    Ordner mit den genannten Dateien; snapshot=None heisst "nicht im Cache" (wirft die gleichnamige
    Ausnahme). Ein Aufruf ohne local_files_only=True waere ein Netzaufruf: pytest.fail, das geht
    auch durch ein "except Exception"."""
    aufrufe: list = []

    def download_model(size_or_id, local_files_only=False, **kwargs):
        aufrufe.append((size_or_id, local_files_only))
        if local_files_only is not True:
            pytest.fail("download_model ohne local_files_only=True waere ein Netzaufruf")
        if snapshot is None:
            raise LocalEntryNotFoundError("Cannot find an appropriate cached snapshot folder (Attrappe)")
        snapshot.mkdir(parents=True, exist_ok=True)
        for datei in dateien:
            (snapshot / datei).write_bytes(b"")
        return str(snapshot)

    modul = types.ModuleType("faster_whisper")
    modul.download_model = download_model
    monkeypatch.setitem(sys.modules, "faster_whisper", modul)
    return aufrufe


def test_sprachmodell_im_cache_mit_tokenizer_ist_ok(monkeypatch, tmp_path):
    aufrufe = _faster_whisper_mit_snapshot(monkeypatch, tmp_path / "snap")
    status, text = doctor._check_speech_model_cache({"stt": {"model": "large-v3-turbo"}})
    assert status == "ok" and "large-v3-turbo" in text and "loads without internet" in text
    assert aufrufe == [("large-v3-turbo", True)]      # nur lokal nachgesehen


def test_sprachmodell_im_cache_ohne_tokenizer_ist_warn(monkeypatch, tmp_path):
    """Der Weg aus dem Befund des Pruefers: ohne tokenizer.json ruft faster-whisper bei jedem Laden
    Tokenizer.from_pretrained auf, fragt also Hugging Face."""
    _faster_whisper_mit_snapshot(monkeypatch, tmp_path / "snap", dateien=("model.bin",))
    status, text = doctor._check_speech_model_cache({})
    assert status == "warn" and "fetches the tokenizer from Hugging Face at every start" in text


@pytest.mark.parametrize("snapshot_dateien", [None, ("tokenizer.json",)], ids=["nicht-im-cache", "halber-snapshot"])
def test_sprachmodell_noch_nicht_im_cache_ist_warn(monkeypatch, tmp_path, snapshot_dateien):
    snapshot = None if snapshot_dateien is None else tmp_path / "snap"
    _faster_whisper_mit_snapshot(monkeypatch, snapshot, dateien=snapshot_dateien or ())
    status, text = doctor._check_speech_model_cache({"stt": {"model": "small"}})
    assert status == "warn" and "small" in text and "downloaded once on the next start" in text


def test_sprachmodell_ohne_faster_whisper_ist_warn_ohne_absturz(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)   # import scheitert wie ohne das Paket
    status, text = doctor._check_speech_model_cache({})
    assert status == "warn" and "cannot check" in text and "faster-whisper" in text


def test_sprachmodell_unbekannter_name_wird_eine_fail_zeile(monkeypatch, capsys):
    """Ein anderer Fehler als "nicht im Cache" (z. B. ein Tippfehler in stt.model) wird nicht als
    "wird heruntergeladen" verharmlost: die Pruefung wirft, run_doctor macht eine FAIL-Zeile daraus."""
    def download_model(size_or_id, local_files_only=False, **kwargs):
        raise ValueError(f"Invalid model size '{size_or_id}' (Attrappe)")

    modul = types.ModuleType("faster_whisper")
    modul.download_model = download_model
    monkeypatch.setitem(sys.modules, "faster_whisper", modul)
    echte_pruefung = doctor._check_speech_model_cache    # _alles_gut() ersetzt sie gleich
    with pytest.raises(ValueError):
        doctor._check_speech_model_cache({"stt": {"model": "large-v9"}})
    _alles_gut(monkeypatch)
    monkeypatch.setattr(doctor, "_check_speech_model_cache", echte_pruefung)
    monkeypatch.setattr(doctor, "_check_config", lambda: ("ok", "config.yaml readable", {"stt": {"model": "large-v9"}}))
    assert doctor.run_doctor() == 1
    assert ("[FAIL] speech model cache check crashed (Invalid model size 'large-v9' (Attrappe)) "
            "-> check stt.model in config.yaml") in capsys.readouterr().out


def test_run_doctor_nennt_das_sprachmodell_aus_der_config(monkeypatch, capsys, tmp_path):
    """Die Zeile erscheint im echten Ablauf, mit stt.model aus der ausgelieferten config.yaml.
    Ersetzt sind faster_whisper, das Netz (Ollama) und alles, was echte Hardware oder echte
    Paket-Importe anfassen wuerde (Mikrofon, GPU, Paketliste)."""
    monkeypatch.setattr(doctor, "_PACKAGES", [])
    monkeypatch.setattr(doctor, "_check_microphone", lambda cfg: ("ok", "Mikrofon (Attrappe)"))
    monkeypatch.setattr(doctor, "_check_gpu", lambda: ("warn", "GPU (Attrappe)"))
    monkeypatch.setattr(doctor, "_check_cleanup_model", lambda cfg: ("warn", "not checked in this test", ""))
    monkeypatch.setattr(doctor, "_check_translate_model", lambda cfg, cleanup_status="": ("warn", "not checked in this test"))
    aufrufe = _faster_whisper_mit_snapshot(monkeypatch, tmp_path / "snap")
    doctor.run_doctor()
    assert ("[OK] speech model large-v3-turbo is on this machine, with tokenizer.json -> loads without "
            "internet") in capsys.readouterr().out
    assert aufrufe == [("large-v3-turbo", True)]


@pytest.mark.parametrize("dateien, status, stichwort", [
    (("model.bin", "tokenizer.json"), "ok", "loads without internet"),
    (("model.bin",), "warn", "fetches the tokenizer from Hugging Face at every start"),
    ((), "fail", "has no model.bin"),
])
def test_sprachmodell_als_lokaler_ordner(monkeypatch, tmp_path, dateien, status, stichwort):
    """stt.model als Modellordner: direkt angesehen, ohne faster_whisper und ohne Hub."""
    monkeypatch.setitem(sys.modules, "faster_whisper", None)   # darf dafuer gar nicht gebraucht werden
    for datei in dateien:
        (tmp_path / datei).write_bytes(b"")
    ergebnis, text = doctor._check_speech_model_cache({"stt": {"model": str(tmp_path)}})
    assert ergebnis == status and stichwort in text


# --- Aufraeum-/Uebersetzungsmodell ------------------------------------------------------------------
def test_cleanup_modell_ok(monkeypatch):
    monkeypatch.setattr(cleanup.Cleaner, "diagnose", lambda self, model="": (cleanup.Cleaner.DIAG_OK, "laeuft"))
    assert doctor._check_cleanup_model({"llm": {}}) == ("ok", "laeuft", cleanup.Cleaner.DIAG_OK)


@pytest.mark.parametrize("status_code", [cleanup.Cleaner.DIAG_UNREACHABLE, cleanup.Cleaner.DIAG_MODEL_MISSING,
                                         cleanup.Cleaner.DIAG_UNKNOWN])
def test_cleanup_modell_ist_nie_fail(monkeypatch, status_code):
    """Ohne das Aufraeum-Modell liefert die App den Rohtext, sie bricht nicht ab -> nie FAIL."""
    monkeypatch.setattr(cleanup.Cleaner, "diagnose", lambda self, model="": (status_code, "Text"))
    status, text, roh = doctor._check_cleanup_model({"llm": {}})
    assert status == "warn" and text == "Text" and roh == status_code


def test_cleanup_modell_abgeschaltet_ohne_netzaufruf(monkeypatch):
    """Nachbesserung Arbeitspaket 4, Runde 1 (B5): llm.enabled: false ist eine bewusste
    Entscheidung, kein Problem - kein Netzaufruf, kein WARN."""
    aufrufe = []
    monkeypatch.setattr(cleanup.Cleaner, "diagnose", lambda self, model="": aufrufe.append(1) or ("x", "y"))
    status, text, _ = doctor._check_cleanup_model({"llm": {"enabled": False}})
    assert status == "ok" and "disabled" in text
    assert aufrufe == []


def test_uebersetzungsmodell_gleich_dem_aufraeummodell_ohne_zweiten_aufruf(monkeypatch):
    aufrufe = []
    monkeypatch.setattr(cleanup.Cleaner, "diagnose", lambda self, model="": aufrufe.append(model) or (cleanup.Cleaner.DIAG_OK, "x"))
    status, text = doctor._check_translate_model({"llm": {"model": "m1"}})
    assert status == "ok" and "m1" in text
    assert aufrufe == []                             # kein Netzwerk-Aufruf noetig


def test_uebersetzungsmodell_fehlt_ist_nur_warn(monkeypatch):
    monkeypatch.setattr(cleanup.Cleaner, "diagnose",
                        lambda self, model="": (cleanup.Cleaner.DIAG_MODEL_MISSING, f"{model} fehlt"))
    status, text = doctor._check_translate_model({"llm": {"model": "m1", "translate_model": "m2"}})
    assert status == "warn" and text == "m2 fehlt"


def test_uebersetzungsmodell_abgeschaltet_ohne_netzaufruf(monkeypatch):
    aufrufe = []
    monkeypatch.setattr(cleanup.Cleaner, "diagnose", lambda self, model="": aufrufe.append(1) or ("x", "y"))
    status, text = doctor._check_translate_model({"llm": {"enabled": False, "translate_model": "m2"}})
    assert status == "ok" and "disabled" in text
    assert aufrufe == []


def test_uebersetzungsmodell_ueberspringt_pruefung_wenn_server_schon_unerreichbar(monkeypatch):
    """Hinweis des Pruefers, Nachbesserung Runde 1: derselbe Server (base_url) ist fuer beide
    Modelle unerreichbar - dann keine zweite, identische "Ollama not reachable"-Zeile."""
    aufrufe = []
    monkeypatch.setattr(cleanup.Cleaner, "diagnose", lambda self, model="": aufrufe.append(model) or (cleanup.Cleaner.DIAG_UNREACHABLE, "sollte nicht erscheinen"))
    status, text = doctor._check_translate_model({"llm": {"model": "m1", "translate_model": "m2"}},
                                                 cleanup.Cleaner.DIAG_UNREACHABLE)
    assert status == "warn" and "same server" in text.lower()
    assert aufrufe == []                             # kein zweiter Netzwerk-Aufruf


# --- run_doctor(): Zusammenspiel, Exit-Code, Absturzsicherung -----------------------------------
def _alles_gut(monkeypatch) -> None:
    monkeypatch.setattr(doctor, "_check_python", lambda: ("ok", "Python 3.12"))
    monkeypatch.setattr(doctor, "_check_os", lambda: ("warn", "linux"))
    monkeypatch.setattr(doctor, "_PACKAGES", [("json", "json", False)])
    monkeypatch.setattr(doctor, "_check_config", lambda: ("ok", "config.yaml readable", {"audio": {}}))
    monkeypatch.setattr(doctor, "_check_dictionary_files", lambda cfg: ("ok", "gefunden"))
    monkeypatch.setattr(doctor, "_check_microphone", lambda cfg: ("ok", "Standardmikrofon"))
    monkeypatch.setattr(doctor, "_check_gpu", lambda: ("warn", "no CUDA GPU"))
    monkeypatch.setattr(doctor, "_check_speech_model_cache", lambda cfg: ("ok", "speech model im Cache"))
    monkeypatch.setattr(doctor, "_check_cleanup_model", lambda cfg: ("ok", "laeuft", cleanup.Cleaner.DIAG_OK))
    monkeypatch.setattr(doctor, "_check_translate_model", lambda cfg, cleanup_status="": ("warn", "fehlt noch"))


def test_run_doctor_exit_code_0_ohne_fail(monkeypatch, capsys):
    _alles_gut(monkeypatch)
    assert doctor.run_doctor() == 0
    out = capsys.readouterr().out
    assert "[OK] Python 3.12" in out and "[WARN] no CUDA GPU" in out and "[WARN] fehlt noch" in out


def test_run_doctor_exit_code_1_bei_einem_fail(monkeypatch):
    _alles_gut(monkeypatch)
    monkeypatch.setattr(doctor, "_check_microphone", lambda cfg: ("fail", "kein Mikrofon"))
    assert doctor.run_doctor() == 1


def test_run_doctor_schlusszeile_wenn_ein_paket_fehlt(monkeypatch, capsys):
    """Nachbesserung Runde 2 (Hinweis des Pruefers): fehlt mindestens ein Paket, kommt am Ende
    eine Sammel-Abhilfe - die Einzelzeilen bleiben trotzdem stehen."""
    _alles_gut(monkeypatch)
    monkeypatch.setattr(doctor, "_PACKAGES", [("json", "json", False), ("gibtsnicht4711", "irgendwas", False)])
    doctor.run_doctor()
    out = capsys.readouterr().out
    assert "gibtsnicht4711 not importable" in out       # Einzelzeile bleibt
    assert "Fix: py -m pip install -r requirements.txt" in out


def test_run_doctor_keine_schlusszeile_wenn_kein_paket_fehlt(monkeypatch, capsys):
    _alles_gut(monkeypatch)
    doctor.run_doctor()
    assert "Fix: py -m pip install -r requirements.txt" not in capsys.readouterr().out


def test_run_doctor_optionales_paket_loest_die_schlusszeile_nicht_aus(monkeypatch, capsys):
    """psutil (optional, nur WARN) allein soll nicht "ein Paket fehlt" ausloesen - das waere fuer
    ein optionales Paket zu alarmierend."""
    _alles_gut(monkeypatch)
    monkeypatch.setattr(doctor, "_PACKAGES", [("gibtsnicht4711", "irgendwas", True)])
    doctor.run_doctor()
    out = capsys.readouterr().out
    assert "[WARN] gibtsnicht4711 not importable" in out
    assert "Fix: py -m pip install -r requirements.txt" not in out


def test_run_doctor_ueberspringt_config_abhaengige_pruefungen_wenn_config_kaputt(monkeypatch, capsys):
    """Nachbesserung Runde 2 (Hinweis des Pruefers): die uebersprungenen Pruefpunkte werden nicht
    stillschweigend ausgelassen, sondern bekommen je eine eigene "skipped"-Zeile."""
    _alles_gut(monkeypatch)
    monkeypatch.setattr(doctor, "_check_config", lambda: ("fail", "kaputt", None))
    aufgerufen = []
    monkeypatch.setattr(doctor, "_check_dictionary_files", lambda cfg: aufgerufen.append("dict") or ("ok", "-"))
    assert doctor.run_doctor() == 1                 # config.yaml unreadable ist selbst ein FAIL
    out = capsys.readouterr().out
    for name in ("dictionary/alias files", "microphone", "GPU", "speech model cache", "clean-up model",
                 "translation model"):
        assert f"{name}: skipped (config.yaml not loaded)" in out
    assert aufgerufen == []                          # Folgepruefungen laufen dann nicht mehr


@pytest.mark.parametrize("kaputte_pruefung, erwartetes_label", [
    ("_check_dictionary_files", "dictionary/alias files"),
    ("_check_microphone", "microphone"),
    ("_check_gpu", "GPU"),
    ("_check_speech_model_cache", "speech model cache"),
])
def test_run_doctor_eine_abstuerzende_pruefung_wird_zu_einer_fail_zeile(monkeypatch, kaputte_pruefung,
                                                                        erwartetes_label, capsys):
    """Nachbesserung Arbeitspaket 4, Runde 1 (B2): eine Ausnahme INNERHALB einer Pruefung (z. B.
    ein IndexError oder ein ValueError aus einem kaputten Konfig-Wert) darf --doctor nicht
    mitreissen - sie wird eine [FAIL]-Zeile, die folgenden Pruefungen laufen trotzdem. Nachbesserung
    Runde 2: die Zeile nennt den Pruefpunkt, nicht nur "check crashed"."""
    _alles_gut(monkeypatch)

    def wirft(*a, **kw):
        raise ValueError("kaputter Konfig-Wert (Attrappe)")

    monkeypatch.setattr(doctor, kaputte_pruefung, wirft)
    assert doctor.run_doctor() == 1
    out = capsys.readouterr().out
    assert f"[FAIL] {erwartetes_label} check crashed (kaputter Konfig-Wert (Attrappe))" in out
    assert "[OK] laeuft" in out                      # die Pruefung DANACH lief trotzdem


@pytest.mark.parametrize("kaputte_pruefung", ["_check_dictionary_files", "_check_microphone",
                                              "_check_speech_model_cache"])
def test_run_doctor_abstuerzende_pruefung_nennt_den_konfig_abschnitt(monkeypatch, kaputte_pruefung, capsys):
    """Nachbesserung Runde 2: wo sinnvoll, nennt die Absturzzeile auch den betroffenen
    config.yaml-Abschnitt (Hinweis des Pruefers). "config.yaml" alleine reicht als Beleg nicht -
    das steht schon in der unabhaengigen "[OK] config.yaml readable"-Zeile; die ABSTURZZEILE
    selbst muss es tragen."""
    _alles_gut(monkeypatch)
    monkeypatch.setattr(doctor, kaputte_pruefung, lambda *a, **kw: (_ for _ in ()).throw(ValueError("x")))
    doctor.run_doctor()
    crash_zeilen = [z for z in capsys.readouterr().out.splitlines() if "check crashed (x)" in z]
    assert len(crash_zeilen) == 1 and "config.yaml" in crash_zeilen[0]


def test_run_doctor_abstuerzende_config_pruefung_wird_zu_einer_fail_zeile(monkeypatch, capsys):
    _alles_gut(monkeypatch)

    def wirft():
        raise ValueError("config.yaml kaputt (Attrappe)")

    monkeypatch.setattr(doctor, "_check_config", wirft)
    assert doctor.run_doctor() == 1
    out = capsys.readouterr().out
    assert "[FAIL] config.yaml check crashed (config.yaml kaputt (Attrappe))" in out


def test_run_doctor_abstuerzende_cleanup_pruefung_wird_zu_einer_fail_zeile(monkeypatch, capsys):
    _alles_gut(monkeypatch)

    def wirft(cfg):
        raise ValueError("invalid literal for int() (Attrappe)")

    monkeypatch.setattr(doctor, "_check_cleanup_model", wirft)
    assert doctor.run_doctor() == 1
    out = capsys.readouterr().out
    assert "[FAIL] clean-up model check crashed (invalid literal for int() (Attrappe)) -> check the llm section of config.yaml" in out
    assert "[WARN] fehlt noch" in out                 # _check_translate_model lief trotzdem


def test_run_doctor_zwei_abstuerzende_pruefungen_sind_nicht_wortgleich(monkeypatch, capsys):
    """Nachbesserung Runde 2: stuerzen zwei Pruefungen am selben Fehler ab, duerfen die beiden
    Zeilen nicht wortgleich sein - der Pruefpunktname unterscheidet sie."""
    _alles_gut(monkeypatch)

    def wirft(*a, **kw):
        raise ValueError("derselbe Fehler (Attrappe)")

    monkeypatch.setattr(doctor, "_check_cleanup_model", wirft)
    monkeypatch.setattr(doctor, "_check_translate_model", wirft)
    doctor.run_doctor()
    zeilen = [z for z in capsys.readouterr().out.splitlines() if "derselbe Fehler" in z]
    assert len(zeilen) == 2 and zeilen[0] != zeilen[1]


# --- requirements.txt/-gpu.txt: die Befunde aus Arbeitspaket 4 -----------------------------------
def _zeile(datei: str, paket: str) -> str:
    text = (config_mod.ROOT / datei).read_text(encoding="utf-8")
    treffer = [z.strip() for z in text.splitlines() if z.strip().lower().startswith(paket)]
    assert treffer, f"{paket} fehlt in {datei}"
    return treffer[0]


def test_requirements_txt_hat_uiautomation_mit_windows_marker():
    """Befund: uiautomation fehlte ganz -> im Standardmodus "hybrid" wurde NIE automatisch
    eingefuegt, still, bei jedem Neu-Nutzer (wf/focus.py faengt den ImportError ab)."""
    assert 'sys_platform == "win32"' in _zeile("requirements.txt", "uiautomation")


def test_requirements_txt_hat_pywin32_mit_windows_marker():
    """Befund: pywin32 stand ohne Marker drin -> pip install -r requirements.txt scheiterte auf
    Nicht-Windows (z. B. CI)."""
    assert 'sys_platform == "win32"' in _zeile("requirements.txt", "pywin32")


def test_requirements_txt_hat_psutil():
    _zeile("requirements.txt", "psutil")           # wirft, wenn die Zeile fehlt


def test_requirements_gpu_txt_hat_die_nvidia_pakete():
    assert (config_mod.ROOT / "requirements-gpu.txt").exists()
    _zeile("requirements-gpu.txt", "nvidia-cublas-cu12")
    _zeile("requirements-gpu.txt", "nvidia-cudnn-cu12")


@pytest.mark.parametrize("plattform", ["win32", "linux"])
def test_run_doctor_laeuft_ohne_absturz_auf_diesem_testrechner(monkeypatch, capsys, plattform):
    """Kriterium: darf ohne Absturz laufen, egal ob als Windows oder als Linux erkannt (auf Linux
    sind FAIL/WARN fuer die Windows-Pakete erwartbar). Nur die Ollama-Erreichbarkeit wuerde echtes
    Netzwerk brauchen (die conftest sperrt das generell) - dafuer eine neutrale Attrappe, der Rest
    laeuft echt gegen diese Testumgebung (Pakete, config.yaml, dictionary.txt/aliases.txt, GPU,
    Mikrofon-Attrappe).

    Nachbesserung Arbeitspaket 10: bisher hing "[OK] Windows" nicht in out vom Zufall des
    Testrechners ab (lief nur auf Linux gruen) - auf dem echten windows-latest-CI-Runner ist
    sys.platform wirklich "win32", _check_os() meldet dort also echt "[OK] Windows", und die feste
    Erwartung "nicht in out" schlug fehl. Jetzt legt der Test sys.platform selbst fest (wie
    test_os_windows_ist_ok_sonst_warn oben) und spielt beide Faelle durch, unabhaengig vom
    tatsaechlichen Testrechner."""
    monkeypatch.setattr(doctor.sys, "platform", plattform)
    monkeypatch.setattr(doctor, "_check_cleanup_model", lambda cfg: ("warn", "not checked in this test", ""))
    monkeypatch.setattr(doctor, "_check_translate_model", lambda cfg, cleanup_status="": ("warn", "not checked in this test"))
    code = doctor.run_doctor()
    assert code in (0, 1)
    out = capsys.readouterr().out
    assert "[FAIL] Python" not in out                # Python 3.11+ laeuft hier (CI-Matrix)
    if plattform == "win32":
        assert "[OK] Windows" in out
    else:
        assert "[OK] Windows" not in out
        assert f"[WARN] {plattform} -> only Windows is supported live" in out


# --- B1: --doctor darf nicht an genau den Paketen scheitern, die es selbst melden soll ----------
_GESPERRTE_KERNPAKETE = ("numpy", "sounddevice", "pynput", "requests", "yaml")


def test_doctor_subprozess_ohne_kernpakete_stuerzt_nicht_ab():
    """Nachbesserung Arbeitspaket 4, Runde 1 (B1). Beweis/Szenario des Pruefers: in einer echten
    Umgebung ohne diese Pakete brach `python3 whisperflow.py --doctor` bisher schon beim Laden von
    whisperflow.py selbst ab (es importiert numpy/wf.audio/wf.cleanup/... am eigenen Kopf), bevor
    --doctor ueberhaupt zum Zug kam. Die conftest-Attrappen wuerden das hier verdecken, deshalb ein
    echter Subprozess mit einem Import-Hook, der numpy, sounddevice, pynput, requests und yaml
    sperrt: erwartet [FAIL]-Zeilen mit einer Abhilfe, Exit-Code 1, kein Traceback."""
    script = textwrap.dedent(f"""
        import runpy
        import sys

        GESPERRT = {_GESPERRTE_KERNPAKETE!r}

        class _Blocker:
            def find_spec(self, name, path, target=None):
                if name.split(".")[0] in GESPERRT:
                    raise ModuleNotFoundError(f"No module named {{name!r}}")
                return None

        sys.meta_path.insert(0, _Blocker())
        sys.argv = ["whisperflow.py", "--doctor"]
        runpy.run_path("whisperflow.py", run_name="__main__")
    """)
    r = subprocess.run([sys.executable, "-c", script], cwd=str(config_mod.ROOT),
                       capture_output=True, text=True, timeout=30)
    assert "Traceback" not in r.stderr, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    assert r.returncode == 1, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    for modul, pip_name in (("numpy", "numpy"), ("sounddevice", "sounddevice"), ("pynput", "pynput"),
                            ("requests", "requests"), ("yaml", "PyYAML")):
        assert f"{modul} not importable" in r.stdout and f"pip install {pip_name}" in r.stdout, r.stdout
    assert "[FAIL]" in r.stdout


# --- config.local.yaml (Arbeitspaket 7, 25.09.2026) ------------------------------------------------
_ECHT_CHECK_CONFIG = doctor._check_config          # _alles_gut() ersetzt ihn, diese Tests brauchen ihn echt


def _lokal(tmp_path, monkeypatch, inhalt: str):
    pfad = tmp_path / "config.local.yaml"
    pfad.write_text(inhalt, encoding="utf-8")
    monkeypatch.setattr(config_mod, "LOCAL_CONFIG_PATH", pfad)


def test_check_config_kaputte_config_local_nennt_datei_und_zeile(tmp_path, monkeypatch):
    """Nicht "config.yaml unreadable": kaputt ist die eigene Datei, und die Zeile steht dabei."""
    _lokal(tmp_path, monkeypatch, 'hotkey:\n  key: "f8"\n mode: toggle\n')
    status, text, cfg = doctor._check_config()
    assert status == "fail" and cfg is None
    assert text.startswith("config.local.yaml, line 3, column ") and "config.yaml unreadable" not in text
    assert "delete it to use config.yaml alone" in text


def test_run_doctor_mit_kaputter_config_local_fail_zeile_ohne_traceback(tmp_path, monkeypatch, capsys):
    _alles_gut(monkeypatch)
    monkeypatch.setattr(doctor, "_check_config", _ECHT_CHECK_CONFIG)
    _lokal(tmp_path, monkeypatch, "audio:\n\tinput_device: 2\n")
    assert doctor.run_doctor() == 1
    out = capsys.readouterr().out
    assert "[FAIL] config.local.yaml, line 2, column 1: found character '\\t' that cannot start any token" in out
    assert "microphone: skipped (config.yaml not loaded)" in out       # die abhaengigen Pruefpunkte
    assert "Traceback" not in out


def test_check_config_nennt_die_eigenen_schluessel_ohne_werte(tmp_path, monkeypatch):
    _lokal(tmp_path, monkeypatch, 'audio:\n  input_device: "Mein Headset"\n')
    status, text, cfg = doctor._check_config()
    assert status == "ok" and cfg["audio"]["input_device"] == "Mein Headset"
    assert text == "config.yaml readable (config.local.yaml overrides: audio.input_device)"
