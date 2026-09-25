"""Die Test-Grundlage selbst: alle Module lassen sich importieren, Attrappen nur bei Bedarf,
und die Attrappen taugen zum Wiederverwenden (Tastencodes, Tray-Menue, Zwischenablage)."""
from __future__ import annotations

import importlib
import sys
import types

import pytest

from wf import i18n

ALLE_MODULE = ["wf.aliases", "wf.audio", "wf.autostart", "wf.cleanup", "wf.config", "wf.context",
               "wf.doctor", "wf.fidelity", "wf.focus", "wf.hotkey", "wf.i18n", "wf.inject",
               "wf.instance", "wf.lang", "wf.overlay", "wf.snip", "wf.stt", "wf.tray", "whisperflow",
               "calibrate"]


@pytest.mark.parametrize("name", ALLE_MODULE)
def test_modul_laesst_sich_importieren(name):
    """Auch whisperflow: ohne Windows, Mikrofon, GPU (Kriterium des Arbeitspakets 1)."""
    assert importlib.import_module(name).__name__ == name


def test_echtes_paket_hat_vorrang(attrappe_falls_noetig):
    module, liste = {}, {}
    attrappe_falls_noetig("json", lambda: {"json": types.ModuleType("json")}, module, liste)
    assert module == {} and liste == {}


def test_fehlendes_paket_bekommt_die_attrappe(attrappe_falls_noetig):
    module, liste = {}, {}
    attrappe = types.ModuleType("gibt_es_nicht_4711")
    attrappe_falls_noetig("gibt_es_nicht_4711", lambda: {"gibt_es_nicht_4711": attrappe}, module, liste)
    assert module["gibt_es_nicht_4711"] is attrappe and attrappe.__attrappe__ is True
    assert liste["gibt_es_nicht_4711"].startswith("ModuleNotFoundError")


def test_nur_die_vorgesehenen_pakete_werden_ersetzt(attrappen):
    erlaubt = {"pynput", "sounddevice", "win32clipboard", "win32con", "win32gui", "win32process",
               "win32api", "uiautomation", "pystray"}
    assert set(attrappen) <= erlaubt
    for name in attrappen:
        assert getattr(sys.modules[name], "__attrappe__", False) is True
    for name in ("wf", "wf.hotkey", "whisperflow", "numpy", "requests", "yaml", "PIL"):
        assert not getattr(importlib.import_module(name), "__attrappe__", False)


def test_attrappe_schluckt_keine_tippfehler(attrappen):
    """Kein MagicMock: ein falscher Name im App-Code faellt weiter auf."""
    if "pynput" not in attrappen:
        pytest.skip("echtes pynput installiert")
    from pynput import keyboard
    with pytest.raises(AttributeError):
        _ = keyboard.Key.ctrl_rr


def test_pynput_tasten_tragen_die_windows_codes_der_app(attrappen):
    """Die Tastencodes in wf/hotkey.py (physische Gegenprobe) und wf/snip.py muessen zu den
    Tasten passen, auf die pynput hoert. Die Attrappe traegt die Codes aus pynputs Windows-Teil."""
    if "pynput" not in attrappen and sys.platform != "win32":
        pytest.skip("echtes pynput ausserhalb von Windows hat keine Windows-Tastencodes")
    from pynput import keyboard

    from wf import hotkey, snip
    for name, vk in hotkey._VK.items():
        assert hotkey._SPECIAL[name].value.vk == vk, name
    for name, vk in snip.KEYS.items():
        assert getattr(keyboard.Key, name).value.vk == vk, name
    assert keyboard.KeyCode.from_char("x") == keyboard.KeyCode.from_char("x")


def test_pynput_listener_merkt_sich_die_rueckrufe(attrappen):
    if "pynput" not in attrappen:
        pytest.skip("echtes pynput installiert (wuerde einen echten Hook anlegen)")
    from pynput import keyboard
    gedrueckt = []
    listener = keyboard.Listener(on_press=gedrueckt.append, on_release=None, win32_event_filter=len)
    listener.start()
    listener.on_press(keyboard.Key.f9)
    assert listener.running and gedrueckt == [keyboard.Key.f9]
    assert listener.kwargs["win32_event_filter"] is len
    with pytest.raises(keyboard.SuppressException):
        listener.suppress_event()


def test_zwischenablage_attrappe_haelt_text(attrappen):
    if "win32clipboard" not in attrappen:
        pytest.skip("echtes pywin32 installiert")
    import win32clipboard
    import win32con
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        assert not win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT)
        win32clipboard.SetClipboardText("Grüße äöüß", win32con.CF_UNICODETEXT)
        assert win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT) == "Grüße äöüß"
        win32clipboard.EmptyClipboard()
        with pytest.raises(win32clipboard.error):
            win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def test_tray_menue_laesst_sich_auslesen_und_klicken(attrappen, monkeypatch):
    """Die pystray-Attrappe merkt sich das Menue: Beschriftungen lesen, Haken pruefen, klicken."""
    if "pystray" not in attrappen:
        pytest.skip("echtes pystray installiert")
    monkeypatch.setattr(i18n, "_current", "en")
    from wf import lang, tray
    aufrufe = []
    t = tray.Tray(lambda on: aufrufe.append(("aktiv", on)), lambda: aufrufe.append("quit"),
                  on_translate_to=lambda code: aufrufe.append(("uebersetzen", code)))
    menue = t._icon.menu.items
    assert [m.text for m in menue] == [
        "Active", "Toggle mode (press once = on, again = off)", "Translate into", "Language",
        "Copy last text to clipboard", "Open the log", "Open the images", "- - - -",
        "Settings", "Start with Windows", "- - - -", "Quit"]
    uebersetzen = menue[2].submenu.items
    assert [m.text for m in uebersetzen] == ["Off (keep my language)"] + [n for _, n in lang.TARGETS]
    assert [m.checked for m in uebersetzen] == [True, False, False, False, False, False]
    uebersetzen[4](t._icon)                                   # "Italiano"
    assert aufrufe == [("uebersetzen", "it")] and uebersetzen[4].checked and t.translate_to == "it"
    t.run()                                                   # Attrappe: kehrt sofort zurueck
    assert t._icon.running
    menue[0](t._icon)                                         # "Active" aus
    menue[-1](t._icon)                                        # "Quit"
    assert aufrufe[1:] == [("aktiv", False), "quit"] and not t._icon.running
    t.notify("Hallo", title="Titel")
    assert t._icon.notifications == [("Hallo", "Titel")]
