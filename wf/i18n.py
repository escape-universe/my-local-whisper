"""Oberflaechensprache (09.09.2026).

Alles, was der Nutzer SIEHT — Tray-Menue, Tray-Meldungen, das Feld am Mauszeiger — kommt aus
diesem Modul. Beim ersten Start wird die Windows-Anzeigesprache genommen; wer sie umstellen will,
macht das im Tray unter „Sprache". Die Wahl steht in state.json und ueberlebt Neustarts.

Getrennt von zwei anderen Sprach-Themen, die es hier schon gibt:
  * `wf/lang.py`  = Sprache des DIKTATS (Erkennung, Sprach-Guard, Uebersetzungsmodus)
  * Konsolen-Ausgaben bleiben Englisch — die liest kein Endnutzer, sondern wer den Fehler sucht.

Neue Sprache: einen Block in TABLE ergaenzen und in LANGUAGES eintragen, fertig. Der Selbsttest
prueft, dass keine Zeile fehlt und keine Platzhalter kaputt sind.
"""
from __future__ import annotations

# Reihenfolge = Reihenfolge im Tray-Menue. Beschriftung immer in der Sprache selbst.
LANGUAGES: list[tuple[str, str]] = [
    ("de", "Deutsch"),
    ("en", "English"),
    ("ru", "Русский"),
    ("es", "Español"),
    ("it", "Italiano"),
]
DEFAULT = "en"

TABLE: dict[str, dict[str, str]] = {
    "de": {
        "tooltip_toggle_mode": "Umschalt-Modus",
        "note_translate_failed": "Übersetzung nach {lang} fehlgeschlagen, der Originaltext bleibt stehen.",
        "menu_active": "Aktiv",
        "menu_toggle_mode": "Umschalt-Modus (Taste: einmal = an, nochmal = aus)",
        "menu_translate": "Translate into",
        "menu_translate_off": "Off (keep my language)",
        "menu_copy_last": "Copy last text to clipboard",
        "menu_open_log": "Verlauf öffnen",
        "menu_open_images": "Bilder öffnen",
        "snip_hint": "Bereich aufziehen   ·   Enter = ganzer Bildschirm   ·   Esc bricht ab",
        "badge_snip_ready": "Bild in der Zwischenablage",
        "badge_snip_arm": "loslassen für den Ausschnitt",
        "badge_snip_full": "ganzer Bildschirm gespeichert",
        "note_snip_full": "Ganzer Bildschirm {size} in der Zwischenablage, gespeichert als {file}",
        "badge_snip_cancelled": "abgebrochen",
        "badge_snip_failed": "Bild fehlgeschlagen",
        "note_snip_saved": "Ausschnitt {size} in der Zwischenablage, gespeichert als {file}",
        "note_no_images_yet": "Noch keine Bilder vorhanden, der Ordner {file} entsteht beim ersten Ausschnitt.",
        "note_images_open_failed": "Bilder-Ordner lässt sich nicht öffnen: {error}",
        "menu_language": "Sprache",
        "menu_language_auto": "Automatisch (System)",
        "menu_quit": "Quit",
        "badge_listening": "erkenne",
        "badge_recording": "Aufnahme",
        "badge_stopped": "Aufnahme aus",
        "badge_cleaning": "cleaning up",
        "badge_translating": "translating",
        "badge_ready": "Ready - press Ctrl+V",
        "badge_ready_appended": "Ready - Ctrl+V (appended)",
        "badge_pasted": "Pasted",
        "badge_error": "Fehler",
        "badge_nothing": "nothing understood",
        "badge_error_console": "Error, see console",
        "badge_clipboard_locked": "Clipboard locked",
        "note_clipboard_failed": "Zwischenablage nicht beschreibbar, der Text steht im Verlauf ({file}).",
        "note_limit_reached": "Aufnahme-Limit erreicht, die Aufnahme wird jetzt abgeschlossen.",
        "note_admin_window": "Das Zielfenster läuft als Administrator, Text NICHT eingefügt. Nimm ein Fenster ohne Administratorrechte.",
        "note_last_text": "Letzter Text in der Zwischenablage",
        "note_no_text": "Kein Text im Verlauf.",
        "note_translate_on": "Übersetzungsmodus an: {lang}",
        "note_translate_off": "Übersetzungsmodus aus, der Text bleibt in der gesprochenen Sprache.",
        "note_error": "Fehler: {error}",
        "note_no_history_configured": "Kein Verlauf eingerichtet (config.yaml: ui.history_file).",
        "note_no_history_yet": "No history yet vorhanden, {file} entsteht beim ersten Diktat.",
        "note_history_open_failed": "Verlauf lässt sich nicht öffnen: {error}",
        "note_language_set": "Sprache der Oberfläche: {lang}",
    },
    "en": {
        "tooltip_toggle_mode": "Toggle mode",
        "note_translate_failed": "Translation into {lang} failed, the original text is kept.",
        "menu_active": "Active",
        "menu_toggle_mode": "Toggle mode (press once = on, again = off)",
        "menu_translate": "Translate into",
        "menu_translate_off": "Off (keep my language)",
        "menu_copy_last": "Copy last text to clipboard",
        "menu_open_log": "Open the log",
        "menu_open_images": "Open the images",
        "snip_hint": "Drag a region   ·   Enter = whole screen   ·   Esc cancels",
        "badge_snip_ready": "Image on the clipboard",
        "badge_snip_arm": "release to snip",
        "badge_snip_full": "full screen saved",
        "note_snip_full": "Full screen {size} on the clipboard, saved as {file}",
        "badge_snip_cancelled": "cancelled",
        "badge_snip_failed": "Snapshot failed",
        "note_snip_saved": "Region {size} on the clipboard, saved as {file}",
        "note_no_images_yet": "No images yet, the folder {file} appears with your first snapshot.",
        "note_images_open_failed": "Cannot open the image folder: {error}",
        "menu_language": "Language",
        "menu_language_auto": "Automatic (system)",
        "menu_quit": "Quit",
        "badge_listening": "transcribing",
        "badge_recording": "recording",
        "badge_stopped": "recording off",
        "badge_cleaning": "cleaning up",
        "badge_translating": "translating",
        "badge_ready": "Ready - press Ctrl+V",
        "badge_ready_appended": "Ready - Ctrl+V (appended)",
        "badge_pasted": "Pasted",
        "badge_error": "Error",
        "badge_nothing": "nothing understood",
        "badge_error_console": "Error, see the console",
        "badge_clipboard_locked": "Clipboard locked",
        "note_clipboard_failed": "Clipboard not writable, the text is in the log ({file}).",
        "note_limit_reached": "Recording limit reached, finishing the recording now.",
        "note_admin_window": "The target window runs as administrator, text NOT pasted. Use a window without admin rights.",
        "note_last_text": "Last text on the clipboard",
        "note_no_text": "No text in the log.",
        "note_translate_on": "Translation on: {lang}",
        "note_translate_off": "Translation off, the text stays in the language you speak.",
        "note_error": "Error: {error}",
        "note_no_history_configured": "No log configured (config.yaml: ui.history_file).",
        "note_no_history_yet": "No log yet, {file} appears with your first dictation.",
        "note_history_open_failed": "Could not open the log: {error}",
        "note_language_set": "Interface language: {lang}",
    },
    "ru": {
        "tooltip_toggle_mode": "Режим переключения",
        "note_translate_failed": "Не удалось перевести на {lang}, исходный текст сохранён.",
        "menu_active": "Активно",
        "menu_toggle_mode": "Режим переключения (нажать один раз — включить, ещё раз — выключить)",
        "menu_translate": "Переводить на",
        "menu_translate_off": "Выключено (оставить мой язык)",
        "menu_copy_last": "Скопировать последний текст",
        "menu_open_log": "Открыть журнал",
        "menu_open_images": "Открыть изображения",
        "snip_hint": "Выделите область   ·   Enter — весь экран   ·   Esc — отмена",
        "badge_snip_ready": "Изображение в буфере обмена",
        "badge_snip_arm": "отпустите для снимка",
        "badge_snip_full": "весь экран сохранён",
        "note_snip_full": "Весь экран {size} в буфере обмена, сохранён как {file}",
        "badge_snip_cancelled": "отменено",
        "badge_snip_failed": "Снимок не удался",
        "note_snip_saved": "Область {size} в буфере обмена, сохранена как {file}",
        "note_no_images_yet": "Изображений пока нет, папка {file} появится после первого снимка.",
        "note_images_open_failed": "Не удаётся открыть папку с изображениями: {error}",
        "menu_language": "Язык",
        "menu_language_auto": "Автоматически (система)",
        "menu_quit": "Выход",
        "badge_listening": "распознаю",
        "badge_recording": "запись",
        "badge_stopped": "запись выключена",
        "badge_cleaning": "привожу в порядок",
        "badge_translating": "перевожу",
        "badge_ready": "Готово — нажмите Ctrl+V",
        "badge_ready_appended": "Готово — Ctrl+V (добавлено)",
        "badge_pasted": "Вставлено",
        "badge_error": "Ошибка",
        "badge_nothing": "ничего не разобрал",
        "badge_error_console": "Ошибка, смотрите консоль",
        "badge_clipboard_locked": "Буфер обмена заблокирован",
        "note_clipboard_failed": "Буфер обмена недоступен для записи, текст сохранён в журнале ({file}).",
        "note_limit_reached": "Достигнут предел записи, запись завершается.",
        "note_admin_window": "Целевое окно запущено от имени администратора, текст НЕ вставлен. Используйте окно без прав администратора.",
        "note_last_text": "Последний текст в буфере обмена",
        "note_no_text": "В журнале нет текста.",
        "note_translate_on": "Перевод включён: {lang}",
        "note_translate_off": "Перевод выключен, текст остаётся на языке, на котором вы говорите.",
        "note_error": "Ошибка: {error}",
        "note_no_history_configured": "Журнал не настроен (config.yaml: ui.history_file).",
        "note_no_history_yet": "Журнала пока нет, {file} появится после первой диктовки.",
        "note_history_open_failed": "Не удалось открыть журнал: {error}",
        "note_language_set": "Язык интерфейса: {lang}",
    },
    "es": {
        "tooltip_toggle_mode": "Modo conmutado",
        "note_translate_failed": "La traducción a {lang} ha fallado, se mantiene el texto original.",
        "menu_active": "Activo",
        "menu_toggle_mode": "Modo conmutado (pulsar una vez = activar, otra vez = detener)",
        "menu_translate": "Traducir a",
        "menu_translate_off": "Desactivado (mantener mi idioma)",
        "menu_copy_last": "Copiar el último texto al portapapeles",
        "menu_open_log": "Abrir el registro",
        "menu_open_images": "Abrir las imágenes",
        "snip_hint": "Arrastra un área   ·   Enter = pantalla completa   ·   Esc cancela",
        "badge_snip_ready": "Imagen en el portapapeles",
        "badge_snip_arm": "suelta para recortar",
        "badge_snip_full": "pantalla completa guardada",
        "note_snip_full": "Pantalla completa {size} en el portapapeles, guardada como {file}",
        "badge_snip_cancelled": "cancelado",
        "badge_snip_failed": "La captura falló",
        "note_snip_saved": "Área {size} en el portapapeles, guardada como {file}",
        "note_no_images_yet": "Aún no hay imágenes, la carpeta {file} aparece con la primera captura.",
        "note_images_open_failed": "No se puede abrir la carpeta de imágenes: {error}",
        "menu_language": "Idioma",
        "menu_language_auto": "Automático (sistema)",
        "menu_quit": "Salir",
        "badge_listening": "transcribiendo",
        "badge_recording": "grabando",
        "badge_stopped": "grabación apagada",
        "badge_cleaning": "limpiando",
        "badge_translating": "traduciendo",
        "badge_ready": "Listo: pulsa Ctrl+V",
        "badge_ready_appended": "Listo: Ctrl+V (añadido)",
        "badge_pasted": "Pegado",
        "badge_error": "Error",
        "badge_nothing": "no he entendido nada",
        "badge_error_console": "Error, mira la consola",
        "badge_clipboard_locked": "Portapapeles bloqueado",
        "note_clipboard_failed": "No se puede escribir en el portapapeles, el texto está en el registro ({file}).",
        "note_limit_reached": "Límite de grabación alcanzado, se cierra la grabación.",
        "note_admin_window": "La ventana de destino se ejecuta como administrador, el texto NO se ha pegado. Usa una ventana sin permisos de administrador.",
        "note_last_text": "Último texto en el portapapeles",
        "note_no_text": "No hay texto en el registro.",
        "note_translate_on": "Traducción activada: {lang}",
        "note_translate_off": "Traducción desactivada, el texto se queda en el idioma que hablas.",
        "note_error": "Error: {error}",
        "note_no_history_configured": "No hay registro configurado (config.yaml: ui.history_file).",
        "note_no_history_yet": "Todavía no hay registro, {file} aparece con tu primer dictado.",
        "note_history_open_failed": "No se ha podido abrir el registro: {error}",
        "note_language_set": "Idioma de la interfaz: {lang}",
    },
    "it": {
        "tooltip_toggle_mode": "Modalità a interruttore",
        "note_translate_failed": "La traduzione in {lang} non è riuscita, resta il testo originale.",
        "menu_active": "Attivo",
        "menu_toggle_mode": "Modalità a interruttore (premi una volta = avvia, di nuovo = ferma)",
        "menu_translate": "Traduci in",
        "menu_translate_off": "Disattivato (mantieni la mia lingua)",
        "menu_copy_last": "Copia l'ultimo testo negli appunti",
        "menu_open_log": "Apri il registro",
        "menu_open_images": "Apri le immagini",
        "snip_hint": "Trascina un'area   ·   Enter = schermo intero   ·   Esc annulla",
        "badge_snip_ready": "Immagine negli appunti",
        "badge_snip_arm": "rilascia per ritagliare",
        "badge_snip_full": "schermo intero salvato",
        "note_snip_full": "Schermo intero {size} negli appunti, salvato come {file}",
        "badge_snip_cancelled": "annullato",
        "badge_snip_failed": "Cattura non riuscita",
        "note_snip_saved": "Area {size} negli appunti, salvata come {file}",
        "note_no_images_yet": "Ancora nessuna immagine, la cartella {file} compare con la prima cattura.",
        "note_images_open_failed": "Impossibile aprire la cartella delle immagini: {error}",
        "menu_language": "Lingua",
        "menu_language_auto": "Automatico (sistema)",
        "menu_quit": "Esci",
        "badge_listening": "trascrivo",
        "badge_recording": "registrazione",
        "badge_stopped": "registrazione off",
        "badge_cleaning": "sistemo",
        "badge_translating": "traduco",
        "badge_ready": "Pronto: premi Ctrl+V",
        "badge_ready_appended": "Pronto: Ctrl+V (aggiunto)",
        "badge_pasted": "Incollato",
        "badge_error": "Errore",
        "badge_nothing": "non ho capito nulla",
        "badge_error_console": "Errore, guarda la console",
        "badge_clipboard_locked": "Appunti bloccati",
        "note_clipboard_failed": "Appunti non scrivibili, il testo è nel registro ({file}).",
        "note_limit_reached": "Limite di registrazione raggiunto, la registrazione viene chiusa.",
        "note_admin_window": "La finestra di destinazione è in esecuzione come amministratore, testo NON incollato. Usa una finestra senza diritti di amministratore.",
        "note_last_text": "Ultimo testo negli appunti",
        "note_no_text": "Nessun testo nel registro.",
        "note_translate_on": "Traduzione attiva: {lang}",
        "note_translate_off": "Traduzione disattivata, il testo resta nella lingua che parli.",
        "note_error": "Errore: {error}",
        "note_no_history_configured": "Nessun registro configurato (config.yaml: ui.history_file).",
        "note_no_history_yet": "Ancora nessun registro, {file} compare con la prima dettatura.",
        "note_history_open_failed": "Impossibile aprire il registro: {error}",
        "note_language_set": "Lingua dell'interfaccia: {lang}",
    },
}

_current = DEFAULT


def detect_system_language() -> str:
    """Windows-Anzeigesprache -> unterstuetzter Code. Unbekannt/kein Windows -> DEFAULT.
    Damit laeuft das Werkzeug fuer den, der es herunterlaedt, sofort in seiner Sprache."""
    primary = ""
    try:  # Windows: die Sprache der OBERFLAECHE, nicht das Zahlen-/Datumsformat
        import ctypes
        lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()  # type: ignore[attr-defined]
        primary = {0x07: "de", 0x09: "en", 0x19: "ru", 0x0A: "es", 0x10: "it"}.get(lcid & 0x3FF, "")
    except Exception:  # noqa: BLE001  — kein Windows oder Aufruf nicht moeglich
        primary = ""
    if not primary:
        try:
            import locale
            tag = (locale.getdefaultlocale()[0] or "")[:2].lower()
            primary = tag if tag in TABLE else ""
        except Exception:  # noqa: BLE001
            primary = ""
    return primary or DEFAULT


def resolve(setting: str | None) -> str:
    """'auto'/leer -> Systemsprache, sonst der Code selbst (unbekannt -> DEFAULT)."""
    s = (setting or "auto").strip().lower()
    if s in ("", "auto", "system"):
        return detect_system_language()
    return s if s in TABLE else DEFAULT


def set_language(code: str) -> str:
    global _current
    _current = code if code in TABLE else DEFAULT
    return _current


def current() -> str:
    return _current


def label(code: str) -> str:
    """Sprachname, wie er im Menue steht."""
    return dict(LANGUAGES).get(code, code)


def t(key: str, **kw: object) -> str:
    """Text in der aktuellen Sprache. Fehlt eine Zeile, faellt er auf Englisch zurueck —
    lieber ein englischer Satz als ein Platzhalter im Menue."""
    text = TABLE.get(_current, {}).get(key) or TABLE[DEFAULT].get(key) or key
    if kw:
        try:
            return text.format(**kw)
        except (KeyError, IndexError):
            return text
    return text
