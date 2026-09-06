"""S9 — Tray-Icon (pystray). Status idle/recording/processing, Umschalt-Modus, letzten Text kopieren, Quit."""
from __future__ import annotations

import threading
from typing import Callable

from PIL import Image, ImageDraw

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
                 toggle_mode: bool = False):
        import pystray
        self._pystray = pystray
        self._enabled = True
        self._toggle_mode = toggle_mode
        self._on_toggle = on_toggle_enabled
        self._on_quit = on_quit
        self._on_toggle_mode = on_toggle_mode
        self._on_copy_last = on_copy_last
        self._state = "idle"
        items = [
            pystray.MenuItem("Active", self._toggle, checked=lambda i: self._enabled),
            pystray.MenuItem("Toggle mode (press once = on, press again = off)",
                             self._toggle_mode_click, checked=lambda i: self._toggle_mode),
            pystray.MenuItem("Copy last text to clipboard", self._copy_last),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        ]
        self._icon = pystray.Icon(
            "whisperflow-local",
            _icon_image("idle", toggle_mode),
            "whisperflow-local",
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
            mode = " · Umschalt-Modus" if self._toggle_mode else ""
            self._icon.title = f"whisperflow-local — {state}{mode}" + (f" · {detail}" if detail else "")
        except Exception:  # noqa: BLE001
            pass

    def notify(self, message: str, title: str = "my-local-whisper") -> None:
        try:
            self._icon.notify(message, title)
        except Exception:  # noqa: BLE001
            print(f"[tray-notify] {title}: {message}")

    def run(self) -> None:
        """Blockiert (muss im Main-Thread laufen)."""
        self._icon.run()

    def run_detached(self) -> None:
        threading.Thread(target=self._icon.run, daemon=True).start()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def toggle_mode(self) -> bool:
        return self._toggle_mode
