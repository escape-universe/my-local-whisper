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
        "menu_translate": "Übersetzen in",
        "menu_translate_off": "Aus (meine Sprache behalten)",
        "menu_copy_last": "Letzten Text in die Zwischenablage kopieren",
        "menu_open_log": "Verlauf öffnen",
        "menu_open_images": "Bilder öffnen",
        "snip_hint": "Bereich aufziehen   ·   Enter = ganzer Bildschirm   ·   Esc bricht ab",
        # badge_snip_ready/_arm/_full und die badge_*-Zeilen weiter unten: das Anzeigefeld waechst
        # seit 24.09.2026 mit dem Text, deutsche Texte sollen aber in seine Mindestbreite passen
        # (wf/overlay.py _W_MIN, Text ab x = 32, Budget siehe tests/test_i18n.py
        # _FELD_BREITE_PX). "Zwischenablage" passt darin nicht neben weiteren Woertern; das
        # kuerzere "Ablage" steht deshalb nur in diesen breiten-kritischen badge_*-Zeilen, die
        # note_*-Meldungen (Tray-Popup, kein Platzlimit) behalten "Zwischenablage". Gemessen
        # 24.09.2026, Nachbesserung Arbeitspaket 2 (siehe tests/test_i18n.py, _breite()).
        "badge_snip_ready": "Bild in der Ablage",
        "badge_snip_arm": "jetzt loslassen",
        "badge_snip_full": "Vollbild gespeichert",
        "note_snip_full": "Ganzer Bildschirm {size} in der Zwischenablage, gespeichert als {file}",
        "badge_snip_cancelled": "abgebrochen",
        "badge_snip_failed": "Bild fehlgeschlagen",
        "note_snip_saved": "Ausschnitt {size} in der Zwischenablage, gespeichert als {file}",
        "note_no_images_yet": "Noch keine Bilder vorhanden, der Ordner {file} entsteht beim ersten Ausschnitt.",
        "note_images_open_failed": "Bilder-Ordner lässt sich nicht öffnen: {error}",
        "menu_language": "Sprache",
        "menu_language_auto": "Automatisch (System)",
        "menu_quit": "Beenden",
        "badge_listening": "erkenne",
        "badge_recording": "Aufnahme",
        "badge_stopped": "Aufnahme aus",
        "badge_cleaning": "räume auf",
        "badge_translating": "übersetze",
        "badge_ready": "Bereit - Strg+V",
        # "Angehaengt" (nicht "Angefuegt"): sonst kaum vom badge_pasted "Eingefuegt" zu
        # unterscheiden, obwohl beide denselben gruenen Haken zeigen und das Gegenteil bedeuten
        # (angehaengt = wartet noch auf Strg+V, eingefuegt = schon eingefuegt). "Anhaengen" ist
        # auch der Begriff im Code (appended in whisperflow.py). Nachbesserung Runde 2, 24.09.2026.
        "badge_ready_appended": "Angehängt - Strg+V",
        "badge_pasted": "Eingefügt",
        "badge_error": "Fehler",
        "badge_nothing": "nichts verstanden",
        "badge_error_console": "Fehler, s. Konsole",
        "badge_clipboard_locked": "Ablage gesperrt",
        "note_clipboard_failed": "Zwischenablage nicht beschreibbar, der Text steht im Verlauf ({file}).",
        "note_limit_reached": "Aufnahme-Limit erreicht, die Aufnahme wird jetzt abgeschlossen.",
        "note_admin_window": "Das Zielfenster läuft als Administrator, Text NICHT eingefügt. Nimm ein Fenster ohne Administratorrechte.",
        "note_last_text": "Letzter Text in der Zwischenablage",
        "note_no_text": "Kein Text im Verlauf.",
        "note_translate_on": "Übersetzungsmodus an: {lang}",
        "note_translate_off": "Übersetzungsmodus aus, der Text bleibt in der gesprochenen Sprache.",
        "note_error": "Fehler: {error}",
        "note_llm_unreachable": "Das Aufräum-Modell ist nicht erreichbar, bis es läuft, wird der Rohtext geliefert. Starte Ollama, oder prüfe llm.base_url in config.yaml.",
        "note_llm_model_missing": "Das Aufräum-Modell {model} ist noch nicht installiert, bis dahin wird der Rohtext geliefert. Führe aus: ollama pull {model}",
        "note_llm_model_missing_other": "Das Aufräum-Modell {model} wurde nicht gefunden, bis dahin wird der Rohtext geliefert. Prüfe llm.model oder den Server in config.yaml.",
        "note_no_history_configured": "Kein Verlauf eingerichtet (config.yaml: ui.history_file).",
        "note_no_history_yet": "Noch kein Verlauf vorhanden, {file} entsteht beim ersten Diktat.",
        "note_history_open_failed": "Verlauf lässt sich nicht öffnen: {error}",
        "note_language_set": "Sprache der Oberfläche: {lang}",
        # Arbeitspaket 7 (25.09.2026): eigene Einstellungen, Autostart, nur eine Instanz.
        "menu_settings": "Einstellungen",
        "menu_autostart": "Mit Windows starten",
        "note_settings_restart": "{file} ist geöffnet. Nach dem Speichern my-local-whisper neu starten (Beenden, dann wieder starten), erst dann gelten die Änderungen.",
        "note_settings_open_failed": "Einstellungen lassen sich nicht öffnen: {error}",
        "note_autostart_on": "my-local-whisper startet ab jetzt mit Windows.",
        "note_autostart_off": "my-local-whisper startet nicht mehr mit Windows.",
        "note_autostart_failed": "Autostart lässt sich nicht ändern: {error}",
        "note_already_running": "my-local-whisper läuft bereits (Symbol im Infobereich der Taskleiste). Dieser zweite Start beendet sich wieder.",
        "note_config_unreadable": "my-local-whisper startet nicht: Eine Einstellungsdatei lässt sich nicht lesen.\n\n{error}",
        "tooltip_state_idle": "bereit",
        "tooltip_state_recording": "Aufnahme",
        "tooltip_state_processing": "verarbeite",
        "tooltip_state_disabled": "pausiert",
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
        "note_llm_unreachable": "The clean-up model is not reachable, the raw transcript is delivered until it runs. Start Ollama, or check llm.base_url in config.yaml.",
        "note_llm_model_missing": "The clean-up model {model} is not installed yet, the raw transcript is delivered until you run: ollama pull {model}",
        "note_llm_model_missing_other": "The clean-up model {model} was not found, the raw transcript is delivered until then. Check llm.model or the server in config.yaml.",
        "note_no_history_configured": "No log configured (config.yaml: ui.history_file).",
        "note_no_history_yet": "No log yet, {file} appears with your first dictation.",
        "note_history_open_failed": "Could not open the log: {error}",
        "note_language_set": "Interface language: {lang}",
        "menu_settings": "Settings",
        "menu_autostart": "Start with Windows",
        "note_settings_restart": "{file} is open. After saving, restart my-local-whisper (Quit, then start it again); only then do the changes apply.",
        "note_settings_open_failed": "Cannot open the settings: {error}",
        "note_autostart_on": "my-local-whisper now starts with Windows.",
        "note_autostart_off": "my-local-whisper no longer starts with Windows.",
        "note_autostart_failed": "Could not change the autostart: {error}",
        "note_already_running": "my-local-whisper is already running (icon in the notification area of the taskbar). This second start closes again.",
        "note_config_unreadable": "my-local-whisper does not start: a settings file cannot be read.\n\n{error}",
        "tooltip_state_idle": "ready",
        "tooltip_state_recording": "recording",
        "tooltip_state_processing": "processing",
        "tooltip_state_disabled": "paused",
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
        "note_llm_unreachable": "Модель очистки текста недоступна, до её запуска доставляется необработанный текст. Запустите Ollama или проверьте llm.base_url в config.yaml.",
        "note_llm_model_missing": "Модель очистки текста {model} ещё не установлена, до этого доставляется необработанный текст. Выполните: ollama pull {model}",
        "note_llm_model_missing_other": "Модель очистки текста {model} не найдена, до этого доставляется необработанный текст. Проверьте llm.model или сервер в config.yaml.",
        "note_no_history_configured": "Журнал не настроен (config.yaml: ui.history_file).",
        "note_no_history_yet": "Журнала пока нет, {file} появится после первой диктовки.",
        "note_history_open_failed": "Не удалось открыть журнал: {error}",
        "note_language_set": "Язык интерфейса: {lang}",
        "menu_settings": "Настройки",
        "menu_autostart": "Запускать вместе с Windows",
        "note_settings_restart": "{file} открыт. После сохранения перезапустите my-local-whisper (Выход, затем запустите снова), только тогда изменения вступят в силу.",
        "note_settings_open_failed": "Не удаётся открыть настройки: {error}",
        "note_autostart_on": "Теперь my-local-whisper запускается вместе с Windows.",
        "note_autostart_off": "my-local-whisper больше не запускается вместе с Windows.",
        "note_autostart_failed": "Не удалось изменить автозапуск: {error}",
        "note_already_running": "my-local-whisper уже запущен (значок в области уведомлений панели задач). Этот повторный запуск завершается.",
        "note_config_unreadable": "my-local-whisper не запускается: не удаётся прочитать файл настроек.\n\n{error}",
        "tooltip_state_idle": "готово",
        "tooltip_state_recording": "запись",
        "tooltip_state_processing": "обработка",
        "tooltip_state_disabled": "на паузе",
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
        "note_llm_unreachable": "El modelo de limpieza no está disponible, se entrega el texto sin depurar hasta que funcione. Inicia Ollama o revisa llm.base_url en config.yaml.",
        "note_llm_model_missing": "El modelo de limpieza {model} aún no está instalado, se entrega el texto sin depurar hasta entonces. Ejecuta: ollama pull {model}",
        "note_llm_model_missing_other": "El modelo de limpieza {model} no se encontró, se entrega el texto sin depurar hasta entonces. Revisa llm.model o el servidor en config.yaml.",
        "note_no_history_configured": "No hay registro configurado (config.yaml: ui.history_file).",
        "note_no_history_yet": "Todavía no hay registro, {file} aparece con tu primer dictado.",
        "note_history_open_failed": "No se ha podido abrir el registro: {error}",
        "note_language_set": "Idioma de la interfaz: {lang}",
        "menu_settings": "Ajustes",
        "menu_autostart": "Iniciar con Windows",
        "note_settings_restart": "{file} está abierto. Después de guardar, reinicia my-local-whisper (Salir y volver a iniciarlo); solo entonces se aplican los cambios.",
        "note_settings_open_failed": "No se pueden abrir los ajustes: {error}",
        "note_autostart_on": "my-local-whisper se inicia ahora con Windows.",
        "note_autostart_off": "my-local-whisper ya no se inicia con Windows.",
        "note_autostart_failed": "No se ha podido cambiar el inicio automático: {error}",
        "note_already_running": "my-local-whisper ya se está ejecutando (icono en el área de notificación de la barra de tareas). Este segundo inicio se cierra.",
        "note_config_unreadable": "my-local-whisper no se inicia: no se puede leer un archivo de ajustes.\n\n{error}",
        "tooltip_state_idle": "listo",
        "tooltip_state_recording": "grabando",
        "tooltip_state_processing": "procesando",
        "tooltip_state_disabled": "en pausa",
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
        "badge_stopped": "registrazione ferma",
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
        "note_llm_unreachable": "Il modello di pulizia non è raggiungibile, il testo grezzo viene consegnato finché non è attivo. Avvia Ollama o controlla llm.base_url in config.yaml.",
        "note_llm_model_missing": "Il modello di pulizia {model} non è ancora installato, nel frattempo viene consegnato il testo grezzo. Esegui: ollama pull {model}",
        "note_llm_model_missing_other": "Il modello di pulizia {model} non è stato trovato, nel frattempo viene consegnato il testo grezzo. Controlla llm.model o il server in config.yaml.",
        "note_no_history_configured": "Nessun registro configurato (config.yaml: ui.history_file).",
        "note_no_history_yet": "Ancora nessun registro, {file} compare con la prima dettatura.",
        "note_history_open_failed": "Impossibile aprire il registro: {error}",
        "note_language_set": "Lingua dell'interfaccia: {lang}",
        "menu_settings": "Impostazioni",
        "menu_autostart": "Avvia con Windows",
        "note_settings_restart": "{file} è aperto. Dopo aver salvato, riavvia my-local-whisper (Esci, poi avvialo di nuovo): solo allora le modifiche hanno effetto.",
        "note_settings_open_failed": "Impossibile aprire le impostazioni: {error}",
        "note_autostart_on": "my-local-whisper ora si avvia con Windows.",
        "note_autostart_off": "my-local-whisper non si avvia più con Windows.",
        "note_autostart_failed": "Impossibile modificare l'avvio automatico: {error}",
        "note_already_running": "my-local-whisper è già in esecuzione (icona nell'area di notifica della barra delle applicazioni). Questo secondo avvio si chiude.",
        "note_config_unreadable": "my-local-whisper non si avvia: impossibile leggere un file di impostazioni.\n\n{error}",
        "tooltip_state_idle": "pronto",
        "tooltip_state_recording": "registrazione",
        "tooltip_state_processing": "elaborazione",
        "tooltip_state_disabled": "in pausa",
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
        primary = _sprache_des_gebietsschemas()
    return primary or DEFAULT


def _sprache_des_gebietsschemas() -> str:
    """Rueckfall, wenn die Oberflaechensprache nicht passt: die Sprache des Gebietsschemas.

    Bis 24.09.2026 kam sie aus locale.getdefaultlocale(), das seit Python 3.11 veraltet ist
    (Entfernung angekuendigt). Jetzt dieselben Quellen ohne die veraltete Funktion: unter Windows
    das Benutzer-Gebietsschema wie dort (GetUserDefaultLocaleName, z. B. "de-DE"), sonst LC_CTYPE,
    das Python beim Start aus LC_ALL/LC_CTYPE/LANG setzt (locale.getlocale, z. B. "de_DE").
    Unter Windows bewusst nicht locale.getlocale(): dort kommen Namen wie "Estonian_Estonia.1257"
    heraus, deren Anfang "es" faelschlich als Spanisch durchginge."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001  — kein Windows
        kernel32 = None
    try:
        if kernel32 is not None:
            puffer = ctypes.create_unicode_buffer(85)                  # LOCALE_NAME_MAX_LENGTH
            name = puffer.value if kernel32.GetUserDefaultLocaleName(puffer, 85) else ""
        else:
            import locale
            name = locale.getlocale()[0] or ""
    except Exception:  # noqa: BLE001
        name = ""
    tag = name[:2].lower()
    return tag if tag in TABLE else ""


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
