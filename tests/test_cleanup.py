"""wf/cleanup.py: Prompt-Bau, Stueckelung, Antwort-Extraktion, Payload nativ/OpenAI und der
Rohtext-Rueckfall. Kein echtes Netzwerk: der HTTP-Aufruf wird per monkeypatch ersetzt (die
conftest sperrt echte Aufrufe zusaetzlich)."""
from __future__ import annotations

import pytest
import requests

from wf import cleanup

OLLAMA = {"llm": {"base_url": "http://127.0.0.1:11434/v1", "keep_alive": "30m"}}
LLAMA_SERVER = {"llm": {"base_url": "http://192.168.1.20:8080/v1"}}


class _Antwort:
    """Ersatz fuer requests.Response: Status, json() (Exception = json() wirft)."""

    def __init__(self, daten, status: int = 200):
        self._daten, self.status_code, self.ok = daten, status, status < 400

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error")

    def json(self):
        if isinstance(self._daten, Exception):
            raise self._daten
        return self._daten


def _nativ(inhalt: str, done_reason: str = "stop") -> _Antwort:
    return _Antwort({"message": {"role": "assistant", "content": inhalt}, "done_reason": done_reason})


def _post_liefert(monkeypatch, c: cleanup.Cleaner, *antworten) -> list[dict]:
    """c._http.post liefert der Reihe nach die Antworten; eine Exception wird geworfen.
    Rueckgabe: die Liste der Aufrufe (url, json, timeout) zum Nachpruefen."""
    aufrufe: list[dict] = []
    rest = list(antworten)

    def post(url, json=None, timeout=None):
        aufrufe.append({"url": url, "json": json, "timeout": timeout})
        a = rest.pop(0)
        if isinstance(a, BaseException):
            raise a
        return a

    monkeypatch.setattr(c._http, "post", post)
    return aufrufe


# --- build_messages ----------------------------------------------------------------------------
def test_system_prompt_traegt_die_regeln():
    """Faelle aus selftest.py: Editor-Rolle, Frage bleibt Frage, kein Gedankenstrich, Umlaute."""
    msgs = cleanup.build_messages("test text", ["Besprechungsraum", "Ollama"], "chat")
    system = msgs[0]["content"]
    assert msgs[0]["role"] == "system"
    assert "text editor, not an assistant" in system
    assert "you do not answer" in system.lower()
    assert "em-dash" in system.lower()
    assert "forbidden" in system.lower() and "ä ö ü ß" in system
    assert "Besprechungsraum, Ollama" in system
    assert cleanup.CATEGORY_TONE["chat"] in system
    assert msgs[-1] == {"role": "user", "content": "<transcript>test text</transcript>"}


def test_leeres_woerterbuch_und_unbekannte_kategorie():
    system = cleanup.build_messages("x", [], "gibtsnicht")[0]["content"]
    assert "(keine)" in system
    assert cleanup.CATEGORY_TONE["default"] in system


@pytest.mark.parametrize("sprache, erwartet", [
    ("en", "Your output MUST be in English"),
    ("de", "Your output MUST be in German"),
    ("EN", "Your output MUST be in English"),
    ("fr", "Your output MUST be in French"),
    ("", "may be German or English"),
    ("auto", "may be German or English"),
])
def test_sprachbindung_im_prompt(sprache, erwartet):
    """Vorfall 08.09.2026: englisches Diktat kam deutsch zurueck -> Sprache hart vorgeben."""
    assert erwartet in cleanup.build_messages("x", [], "default", sprache)[0]["content"]


@pytest.mark.parametrize("sprache", ["de", "en"])
def test_nur_beispiele_der_erkannten_sprache(sprache):
    msgs = cleanup.build_messages("text", ["Ollama"], "default", sprache)
    beispiele = msgs[1:-1]
    erwartet = [s for s in cleanup._FEWSHOT if s[0] == sprache]
    assert erwartet and len(beispiele) == 2 * len(erwartet)
    assert [m["role"] for m in beispiele] == ["user", "assistant"] * len(erwartet)
    assert [m["content"] for m in beispiele] == [x for _, rein, raus in erwartet for x in (rein, raus)]


def test_beispiele_sind_einsprachig():
    """Die eigentliche Ursache vom 08.09.2026 waren gemischte Beispiele (selftest.py)."""
    en = " ".join(m["content"] for m in cleanup.build_messages("x", [], "default", "en")[1:-1])
    de = " ".join(m["content"] for m in cleanup.build_messages("x", [], "default", "de")[1:-1])
    assert "Besprechungsraum" not in en and "Budget" not in en
    assert "Alex tomorrow" not in de


def test_ohne_erkennung_kommen_beide_sprachen():
    auto = cleanup.build_messages("x", [], "default", "")
    assert len(auto) == 2 + 2 * len(cleanup._FEWSHOT)
    assert len(auto) > len(cleanup.build_messages("x", [], "default", "en"))


def test_uebersetzungsauftrag():
    msgs = cleanup.build_translate_messages("Hallo", ["Ollama"], "it")
    assert "into Italian" in msgs[0]["content"] and "Ollama" in msgs[0]["content"]
    assert msgs[1] == {"role": "user", "content": "Hallo"}


# --- _strip_think / _extract -------------------------------------------------------------------
def test_think_block_wird_entfernt():
    assert cleanup._strip_think("<think>ich ueberlege</think>Das ist der Text.") == "Das ist der Text."
    assert cleanup._strip_think("<THINK>\nzeile 1\nzeile 2\n</THINK>\n  Text  ") == "Text"
    assert cleanup._strip_think("ohne Denkblock") == "ohne Denkblock"


@pytest.mark.parametrize("roh, erwartet", [
    ("<transcript>Hallo Welt</transcript>", "Hallo Welt"),
    ("Hier ist der Text: <transcript> Hallo Welt </transcript> fertig", "Hallo Welt"),
    ('"Hallo Welt"', "Hallo Welt"),
    ('  "Hallo Welt"  ', "Hallo Welt"),
    ("Hallo Welt.", "Hallo Welt."),
    ("„Hallo Welt.“", "Hallo Welt."),              # deutsche Anfuehrungszeichen
    ("“Hello world.”", "Hello world."),            # englische
    ('"', ""), ('""', ""), (' " "" ', ""),         # nur Anfuehrungszeichen: leer -> Rohtext-Rueckfall
])
def test_extract(roh, erwartet):
    assert cleanup._extract(roh) == erwartet


@pytest.mark.parametrize("satz", [
    'Er sagte "Hallo"',
    '"Nextcloud" ist der Name',
    '"Hallo" und "Tschüss"',                         # vorne und hinten, aber zwei Paare
    '„Ja“, sagte er, „gern“',
    '"Er sagte „Hallo“."',                          # innen weitere: im Zweifel stehen lassen
])
def test_extract_laesst_anfuehrungszeichen_im_satz_stehen(satz):
    """Bis 24.09.2026 nahm strip('"') auch Anfuehrungszeichen, die zum Satz gehoeren
    ('Er sagte "Hallo"' -> 'Er sagte "Hallo'). Entfernt wird nur ein Paar, das die GANZE
    Antwort umschliesst und innen keine weiteren Anfuehrungszeichen hat."""
    assert cleanup._extract(satz) == satz


# --- split_chunks ------------------------------------------------------------------------------
def test_lange_texte_werden_satzweise_gestueckelt():
    text = "Satz eins. Satz zwei! Satz drei? " * 80
    stuecke = cleanup.Cleaner.split_chunks(text, 300)
    assert len(stuecke) > 5
    assert max(len(s) for s in stuecke) <= 300
    assert all(s[-1] in ".!?" for s in stuecke)
    assert " ".join(stuecke) == " ".join(text.split())          # nichts geht verloren


def test_kurzer_und_leerer_text():
    assert cleanup.Cleaner.split_chunks("Kurz.", 300) == ["Kurz."]
    assert cleanup.Cleaner.split_chunks("  zu   viel\n Leerraum ", 300) == ["zu viel Leerraum"]
    assert cleanup.Cleaner.split_chunks("", 300) == []
    assert cleanup.Cleaner.split_chunks(None, 300) == []


def test_satz_ohne_punkt_wird_an_leerzeichen_gebrochen():
    text = " ".join(f"wort{i}" for i in range(200))              # ~1300 Zeichen, kein Satzende
    stuecke = cleanup.Cleaner.split_chunks(text, 100)
    assert max(len(s) for s in stuecke) <= 100
    assert " ".join(stuecke) == text                           # an Leerzeichen, kein Wort zerteilt


def test_riesenwort_wird_hart_geschnitten():
    assert cleanup.Cleaner.split_chunks("x" * 250, 100) == ["x" * 100, "x" * 100, "x" * 50]


# --- Cleaner: Adresse und Payload --------------------------------------------------------------
def test_ollama_port_nutzt_die_native_schnittstelle():
    c = cleanup.Cleaner(OLLAMA, [])
    assert c.native and c.url == "http://127.0.0.1:11434/api/chat"
    p = c._payload([{"role": "user", "content": "x"}], 50)
    assert p == {"model": c.model, "messages": [{"role": "user", "content": "x"}], "stream": False,
                 "keep_alive": "30m", "options": {"temperature": 0.2, "top_p": 0.9, "num_predict": 50}}


def test_keep_alive_minus_eins_bleibt_im_nativen_payload():
    c = cleanup.Cleaner({"llm": {"base_url": "http://127.0.0.1:11434/v1", "keep_alive": -1}}, [])
    assert c._payload([], 5)["keep_alive"] == -1


def test_llama_server_bleibt_openai_kompatibel():
    c = cleanup.Cleaner(LLAMA_SERVER, [])
    assert not c.native and c.url == "http://192.168.1.20:8080/v1/chat/completions"
    p = c._payload([{"role": "user", "content": "x"}], 50)
    assert p["max_tokens"] == 50 and p["temperature"] == 0.2 and p["stream"] is False
    assert "options" not in p and p["keep_alive"] == "30m"      # Ollama-Feld, llama-server ignoriert es


@pytest.mark.parametrize("llm, nativ, url", [
    ({"base_url": "http://127.0.0.1:11434/v1", "api": "openai"}, False, "http://127.0.0.1:11434/v1/chat/completions"),
    ({"base_url": "http://10.0.0.5:9000/v1", "api": "ollama"}, True, "http://10.0.0.5:9000/api/chat"),
    ({"base_url": "http://127.0.0.1:11434"}, True, "http://127.0.0.1:11434/api/chat"),
    ({"base_url": "http://127.0.0.1:11434/v1/"}, True, "http://127.0.0.1:11434/api/chat"),
])
def test_schnittstelle_waehlbar(llm, nativ, url):
    c = cleanup.Cleaner({"llm": llm}, [])
    assert (c.native, c.url) == (nativ, url)


def test_localhost_wird_auf_127_0_0_1_umgebogen(capsys):
    """Gemessen 05.09.2026: localhost kostet unter Windows ~2 s pro Verbindung (IPv6 zuerst)."""
    c = cleanup.Cleaner({"llm": {"base_url": "http://localhost:11434/v1"}}, [])
    assert c.url == "http://127.0.0.1:11434/api/chat"
    assert "localhost -> 127.0.0.1" in capsys.readouterr().out


def test_uebersetzung_nutzt_eigenes_modell_und_keep_alive():
    c = cleanup.Cleaner({"llm": {**OLLAMA["llm"], "model": "qwen2.5:3b-instruct",
                                 "translate_model": "gemma3:4b", "translate_keep_alive": "5m"}}, [])
    tr = c._payload([], 10, c.translate_model, c.translate_keep_alive)
    assert (tr["model"], tr["keep_alive"]) == ("gemma3:4b", "5m")
    normal = c._payload([], 10)
    assert (normal["model"], normal["keep_alive"]) == ("qwen2.5:3b-instruct", "30m")


def test_ohne_uebersetzungsmodell_gilt_das_cleanup_modell():
    c = cleanup.Cleaner({"llm": {"model": "m1"}}, [])
    assert c.translate_model == "m1"


def test_ausgelieferte_config_trennt_uebersetzungs_und_cleanup_modell():
    """selftest.py: qwen2.5:3b konnte kein Italienisch -> eigenes Modell fuers Uebersetzen."""
    from wf import config
    c = cleanup.Cleaner(config.load_config(), [])
    assert c.translate_model and c.translate_model != c.model


@pytest.mark.parametrize("cfg", [OLLAMA, LLAMA_SERVER], ids=["nativ", "openai"])
def test_translate_keep_alive_null_wird_uebernommen(cfg):
    """translate_keep_alive: 0 = Uebersetzungsmodell sofort entladen. Bis 24.09.2026 machte
    `keep_alive or self.keep_alive` daraus das keep_alive des Cleanup-Modells (-1 = nie)."""
    c = cleanup.Cleaner({"llm": {**cfg["llm"], "keep_alive": -1, "translate_keep_alive": 0}}, [])
    assert c._payload([], 10, c.translate_model, c.translate_keep_alive)["keep_alive"] == 0


@pytest.mark.parametrize("cfg", [OLLAMA, LLAMA_SERVER], ids=["nativ", "openai"])
@pytest.mark.parametrize("nicht_gesetzt", [None, ""])
def test_nicht_gesetztes_keep_alive_gilt_wie_beim_cleanup_modell(cfg, nicht_gesetzt):
    c = cleanup.Cleaner({"llm": {**cfg["llm"], "keep_alive": -1, "translate_keep_alive": nicht_gesetzt}}, [])
    assert c._payload([], 10, c.translate_model, c.translate_keep_alive)["keep_alive"] == -1
    assert c._payload([], 10)["keep_alive"] == -1


def test_uebersetzung_schickt_keep_alive_null_an_ollama(monkeypatch):
    """Der ganze Weg translate() -> _ask() -> _payload(), nicht nur _payload() allein."""
    c = cleanup.Cleaner({"llm": {**OLLAMA["llm"], "keep_alive": -1, "translate_keep_alive": 0}}, [])
    aufrufe = _post_liefert(monkeypatch, c, _nativ("Ciao mondo."))
    assert c.translate("Hallo Welt.", "it") == ("Ciao mondo.", True)
    assert aufrufe[0]["json"]["keep_alive"] == 0


def test_parse_nativ_und_openai():
    assert cleanup.Cleaner._parse({"message": {"content": "ok"}, "done_reason": "length"}, True) == ("ok", "length")
    assert cleanup.Cleaner._parse({"message": {"content": "ok"}}, True) == ("ok", "")
    daten = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    assert cleanup.Cleaner._parse(daten, False) == ("ok", "stop")


# --- clean(): Rohtext-Rueckfall ----------------------------------------------------------------
ROH = "aehm also wir sehen uns morgen im besprechungsraum"


@pytest.mark.parametrize("fehler", [
    requests.ConnectionError("Connection refused"),
    requests.Timeout("read timed out"),
    _Antwort({}, status=500),
    _Antwort(ValueError("kein JSON")),
    _Antwort({"unerwartet": True}),
    _nativ("Wir sehen uns morgen", done_reason="length"),
    _nativ("   "),
], ids=["nicht-erreichbar", "timeout", "http-500", "kein-json", "falsche-struktur", "abgeschnitten", "leer"])
def test_clean_faellt_auf_den_rohtext_zurueck(monkeypatch, fehler):
    c = cleanup.Cleaner(OLLAMA, [])
    aufrufe = _post_liefert(monkeypatch, c, fehler)
    assert c.clean(ROH, "default", "de") == (ROH, False)
    assert len(aufrufe) == 1 and aufrufe[0]["url"] == "http://127.0.0.1:11434/api/chat"


def test_clean_nicht_erreichbar_meldet_den_rueckfall(monkeypatch, capsys):
    c = cleanup.Cleaner(OLLAMA, [])
    _post_liefert(monkeypatch, c, requests.ConnectionError("Connection refused"))
    c.clean(ROH, "default", "de")
    assert "raw-text fallback" in capsys.readouterr().out


def test_clean_erfolg(monkeypatch):
    c = cleanup.Cleaner(OLLAMA, ["Besprechungsraum"])
    aufrufe = _post_liefert(monkeypatch, c, _nativ("<think>hm</think>Wir sehen uns morgen im Besprechungsraum."))
    assert c.clean(f"  {ROH}  ", "chat", "de") == ("Wir sehen uns morgen im Besprechungsraum.", True)
    gesendet = aufrufe[0]["json"]
    assert gesendet["model"] == c.model and gesendet["keep_alive"] == "30m"
    assert gesendet["messages"][-1]["content"] == f"<transcript>{ROH}</transcript>"
    assert aufrufe[0]["timeout"] == c.timeout


def test_clean_openai_antwort(monkeypatch):
    c = cleanup.Cleaner(LLAMA_SERVER, [])
    _post_liefert(monkeypatch, c, _Antwort({"choices": [{"message": {"content": "Hallo Welt."},
                                                         "finish_reason": "stop"}]}))
    assert c.clean("hallo welt", "default", "de") == ("Hallo Welt.", True)


def test_clean_sprachwechsel_gibt_rohtext(monkeypatch):
    c = cleanup.Cleaner(OLLAMA, [])
    roh = "we should move the meeting to tomorrow morning and that is fine"
    _post_liefert(monkeypatch, c, _nativ("Wir sollten das Treffen auf morgen früh verschieben, und das ist gut."))
    assert c.clean(roh, "default", "en") == (roh, False)


def test_clean_erfundene_zahl_gibt_rohtext(monkeypatch):
    """Belegter Fall 08.09.2026: „fuenfundsiebzig" wurde zu „75k"."""
    c = cleanup.Cleaner(OLLAMA, [])
    roh = "das budget eher fünfundsiebzig"
    _post_liefert(monkeypatch, c, _nativ("Das Budget eher 75k."))
    assert c.clean(roh, "default", "de") == (roh, False)


def test_clean_ohne_aufruf_wenn_aus_oder_leer(monkeypatch):
    c = cleanup.Cleaner({"llm": {**OLLAMA["llm"], "enabled": False}}, [])
    aufrufe = _post_liefert(monkeypatch, c)
    assert c.clean(ROH) == (ROH, False)
    c2 = cleanup.Cleaner(OLLAMA, [])
    aufrufe2 = _post_liefert(monkeypatch, c2)
    assert c2.clean("   ") == ("", False)
    assert aufrufe == [] and aufrufe2 == []


def test_langer_text_ein_stueck_scheitert_der_rest_wird_bereinigt(monkeypatch):
    c = cleanup.Cleaner(OLLAMA, [])
    c.CHUNK_CHARS = 40
    roh = "erster satz ist hier. zweiter satz ist da. dritter satz ist dort."
    stuecke = c.split_chunks(roh, 40)
    assert len(stuecke) == 3
    aufrufe = _post_liefert(monkeypatch, c, _nativ("Erster Satz ist hier."),
                            requests.ConnectionError("weg"), _nativ("Dritter Satz ist dort."))
    assert c.clean(roh, "default", "de") == ("Erster Satz ist hier. zweiter satz ist da. Dritter Satz ist dort.", True)
    assert len(aufrufe) == 3


# --- translate(): Rueckfall und Schriftsystem --------------------------------------------------
def test_uebersetzung_nicht_erreichbar_behaelt_den_text(monkeypatch):
    c = cleanup.Cleaner(OLLAMA, [])
    _post_liefert(monkeypatch, c, requests.ConnectionError("weg"))
    assert c.translate("Hallo Welt.", "it") == ("Hallo Welt.", False)


def test_uebersetzung_im_falschen_schriftsystem_wird_einmal_wiederholt(monkeypatch):
    """Gemessen 08.09.2026: Ziel Italienisch kam als Chinesisch zurueck."""
    c = cleanup.Cleaner({"llm": {**OLLAMA["llm"], "translate_model": "gemma3:4b"}}, [])
    aufrufe = _post_liefert(monkeypatch, c, _nativ("我可以给你们预定"), _nativ("Ciao mondo."))
    assert c.translate("Hallo Welt.", "it") == ("Ciao mondo.", True)
    assert [a["json"]["model"] for a in aufrufe] == ["gemma3:4b", "gemma3:4b"]
    aufrufe = _post_liefert(monkeypatch, c, _nativ("我可以"), _nativ("给你们"))
    assert c.translate("Hallo Welt.", "it") == ("Hallo Welt.", False)
    assert len(aufrufe) == 2


def test_uebersetzung_ohne_ziel_macht_nichts(monkeypatch):
    c = cleanup.Cleaner(OLLAMA, [])
    aufrufe = _post_liefert(monkeypatch, c)
    assert c.translate("Hallo", "") == ("Hallo", False)
    assert aufrufe == []
