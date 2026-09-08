"""S9 — Tray-Icon (pystray). Status idle/recording/processing, Umschalt-Modus, letzten Text kopieren, Quit."""
from __future__ import annotations

import threading
from typing import Callable

from PIL import Image, ImageDraw

from . import i18n
from . import lang as lang_mod

_COLORS = {
    "idle": (60, 120, 200),        # blau
    "recording": (210, 60, 60),    # rot
    "processing": (230, 170, 40),  # gelb
    "disabled": (120, 120, 120),   # grau
}


def _icon_image(state: str, toggle: bool = False) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, 58, 58), fill=_COLORS.get(state, _COLORS["idle"]))
    # kleines Mikro-Symbol
    d.rounded_rectangle((27, 18, 37, 40), radius=5, fill=(255, 255, 255))
    d.line((32, 40, 32, 48), fill=(255, 255, 255), width=3)
    d.line((24, 48, 40, 48), fill=(255, 255, 255), width=3)
    if toggle:  # kleiner weisser Punkt oben rechts = Umschalt-Modus aktiv
        d.ellipse((46, 8, 56, 18), fill=(255, 255, 255))
    return img


class Tray:
    def __init__(self, on_toggle_enabled: Callable[[bool], None], on_quit: Callable[[], None],
                 on_toggle_mode: Callable[[bool], None] | None = None,
                 on_copy_last: Callable[[], None] | None = None,
                 toggle_mode: bool = False,
                 on_translate_to: Callable[[str], None] | None = None,
                 on_open_log: Callable[[], None] | None = None,
                 on_set_ui_language: Callable[[str], None] | None = None,
                 ui_language: str = "auto"):
        import pystray
        self._pystray = pystray
        self._enabled = True
        self._toggle_mode = toggle_mode
        self._on_toggle = on_toggle_enabled
        self._on_quit = on_quit
        self._on_toggle_mode = on_toggle_mode
        self._on_copy_last = on_copy_last
        self._on_translate_to = on_translate_to
        self._on_open_log = on_open_log
        self._on_set_ui_language = on_set_ui_language
        self._ui_language = ui_language      # "auto" oder ein Code aus i18n.LANGUAGES
        self._translate_to = ""      # "" = aus; beim Start immer aus (Entscheidung 08.09.2026)
        self._state = "idle"
        # Untermenue "Translate into": Aus + die fuenf Zielsprachen aus wf/lang.py.
        # Radio-Auswahl: genau eine Zeile ist aktiv, "Aus" ist der Startzustand.
        # Bewusst NUR ueber das Tray, keine Tastenkombination — Strg+I/E/R sind in fast
        # jedem Programm belegt (Entscheidung 08.09.2026).
        sprach_items = [pystray.MenuItem(lambda i: i18n.t("menu_translate_off"), self._make_lang_click(""),
                                         checked=lambda i, c="": self._translate_to == "",
                                         radio=True)]
        for code, label in lang_mod.TARGETS:
            sprach_items.append(pystray.MenuItem(
                label, self._make_lang_click(code),
                checked=lambda i, c=code: self._translate_to == c, radio=True))
        # Oberflaechensprache (09.09.2026): „Automatisch" nimmt die Windows-Anzeigesprache, sonst
        # die gewaehlte. Beschriftungen sind Callables, damit das Menue nach dem Umstellen sofort
        # in der neuen Sprache steht, ohne die App neu zu starten.
        ui_items = [pystray.MenuItem(lambda i: i18n.t("menu_language_auto"), self._make_ui_lang_click("auto"),
                                     checked=lambda i: self._ui_language == "auto", radio=True)]
        for code, label in i18n.LANGUAGES:
            ui_items.append(pystray.MenuItem(
                label, self._make_ui_lang_click(code),
                checked=lambda i, c=code: self._ui_language == c, radio=True))
        items = [
            pystray.MenuItem(lambda i: i18n.t("menu_active"), self._toggle, checked=lambda i: self._enabled),
            pystray.MenuItem(lambda i: i18n.t("menu_toggle_mode"),
                             self._toggle_mode_click, checked=lambda i: self._toggle_mode),
            pystray.MenuItem(lambda i: i18n.t("menu_translate"), pystray.Menu(*sprach_items)),
            pystray.MenuItem(lambda i: i18n.t("menu_language"), pystray.Menu(*ui_items)),
            pystray.MenuItem(lambda i: i18n.t("menu_copy_last"), self._copy_last),
            # Verlauf oeffnen (09.09.2026): die letzten Diktate nachlesen, ohne den Ordner zu suchen.
            pystray.MenuItem(lambda i: i18n.t("menu_open_log"), self._open_log),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda i: i18n.t("menu_quit"), self._quit),
        ]
        self._icon = pystray.Icon(
            "my-local-whisper",
            _icon_image("idle", toggle_mode),
            "my-local-whisper",
            menu=pystray.Menu(*items),
        )

    def _toggle(self, icon, item):  # noqa: ARG002
        self._enabled = not self._enabled
        self.set_state("idle" if self._enabled else "disabled")
        self._on_toggle(self._enabled)

    def _toggle_mode_click(self, icon, item):  # noqa: ARG002
        self._toggle_mode = not self._toggle_mode
        self.set_state(self._state)
        if self._on_toggle_mode:
            self._on_toggle_mode(self._toggle_mode)

    def _open_log(self, icon, item):  # noqa: ARG002
        if self._on_open_log:
            self._on_open_log()

    def _make_ui_lang_click(self, setting: str):
        def _click(icon, item):  # noqa: ARG002
            self._ui_language = setting
            if self._on_set_ui_language:
                self._on_set_ui_language(setting)
            try:                      # Beschriftungen sofort in der neuen Sprache zeigen
                self._icon.update_menu()
            except Exception:  # noqa: BLE001
                pass
        return _click

    def _make_lang_click(self, code: str):
        def _click(icon, item):  # noqa: ARG002
            self._translate_to = code
            self.set_state(self._state)
            if self._on_translate_to:
                self._on_translate_to(code)
        return _click

    def _copy_last(self, icon, item):  # noqa: ARG002
        if self._on_copy_last:
            self._on_copy_last()

    def _quit(self, icon, item):  # noqa: ARG002
        self._on_quit()
        self._icon.stop()

    def set_state(self, state: str, detail: str = "") -> None:
        self._state = state
        try:
            self._icon.icon = _icon_image(state, self._toggle_mode)
            mode = (" · " + i18n.t("tooltip_toggle_mode")) if self._toggle_mode else ""
            tr = (" · → " + lang_mod.name_native(self._translate_to)) if self._translate_to else ""
            self._icon.title = (f"whisperflow-local — {state}{mode}{tr}"
                                + (f" · {detail}" if detail else ""))
        except Exception:  # noqa: BLE001
            pass

    def notify(self, message: str, title: str = "my-local-whisper") -> None:
        try:
            self._icon.notify(message, title)
        except Exception:  # noqa: BLE001
            print(f"[tray-notify] {title}: {message}")

    def run(self) -> None:
        """Blocked (must run on the main thread)."""
        self._icon.run()

    def run_detached(self) -> None:
        threading.Thread(target=self._icon.run, daemon=True).start()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def toggle_mode(self) -> bool:
        return self._toggle_mode

    @property
    def translate_to(self) -> str:
        return self._translate_to
