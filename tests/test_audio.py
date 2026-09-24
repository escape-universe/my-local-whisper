"""wf/audio.py ohne Mikrofon: Sprechpausen-Schnitt an synthetischen Signalen, Vorlauf-Ring und
abschnittsweises Abholen ueber direkte _callback-Aufrufe (so wie sounddevice sie liefert)."""
from __future__ import annotations

import numpy as np
import pytest

from wf import audio

SR = 16000


class _DummyStream:
    """Steht fuer den offenen Mikrofon-Stream (persistent_stream), ohne Geraet."""

    def __init__(self):
        self.gestoppt = self.geschlossen = False

    def stop(self):
        self.gestoppt = True

    def close(self):
        self.geschlossen = True


@pytest.fixture
def signal():
    """Bausteine mit festem Zufallsstartwert: sprache(s) ~ Rauschen 0,2; stille(s) = Nullen."""
    rng = np.random.default_rng(1)

    class _S:
        @staticmethod
        def sprache(s, pegel=0.2):
            return (rng.standard_normal(int(s * SR)) * pegel).astype(np.float32)

        @staticmethod
        def stille(s):
            return np.zeros(int(s * SR), dtype=np.float32)

    return _S


# --- find_silence_cut --------------------------------------------------------------------------
def test_schnitt_in_der_langen_pause_nicht_in_der_kurzen(signal):
    """Fall aus selftest.py: 0,8-s-Pause bei 10 s, 0,2-s-Pause bei 18,8 s."""
    a = np.concatenate([signal.sprache(10), signal.stille(0.8), signal.sprache(8),
                        signal.stille(0.2), signal.sprache(6)])
    cut = audio.find_silence_cut(a, SR)
    assert cut is not None and abs(cut / SR - 10.4) < 0.3
    assert 10.0 < cut / SR < 10.8                              # im Stillen, kein Wort zerteilt


def test_die_letzte_pause_zaehlt(signal):
    a = np.concatenate([signal.sprache(5), signal.stille(1), signal.sprache(5), signal.stille(1), signal.sprache(3)])
    assert 11.0 < audio.find_silence_cut(a, SR) / SR < 12.0


def test_kein_schnitt_ohne_pause(signal):
    assert audio.find_silence_cut(signal.sprache(30), SR) is None


def test_kein_schnitt_zu_nah_am_anfang(signal):
    """min_keep_s = 3 s: sonst entstuenden winzige Abschnitte."""
    a = np.concatenate([signal.sprache(1), signal.stille(1), signal.sprache(5)])
    assert audio.find_silence_cut(a, SR) is None


def test_stille_rauschen_und_zu_kurzes_audio(signal):
    assert audio.find_silence_cut(signal.stille(10), SR) is None
    assert audio.find_silence_cut(signal.sprache(10, pegel=0.01), SR) is None   # nur Luefter
    assert audio.find_silence_cut(signal.sprache(3), SR) is None
    assert audio.find_silence_cut(None, SR) is None


def test_pause_ueber_grundrauschen_wird_gefunden(signal):
    """Luefter/Rauschen liegen konstant ueber Null: Schwelle relativ zum Grundrauschen."""
    a = np.concatenate([signal.sprache(6), signal.stille(1), signal.sprache(4)]) + signal.sprache(11, pegel=0.01)
    assert 6.0 < audio.find_silence_cut(a.astype(np.float32), SR) / SR < 7.0


# --- Recorder: Vorlauf-Ring --------------------------------------------------------------------
def _block(wert: float, n: int = 10) -> np.ndarray:
    return np.full((n, 1), wert, dtype=np.float32)


@pytest.fixture
def rec():
    """Persistenter Recorder mit 100 Hz, Vorlauf 0,5 s (= 50 Frames), Stream "offen"."""
    r = audio.Recorder(samplerate=100, persistent=True, preroll_s=0.5)
    r._stream = _DummyStream()
    return r


def test_ausserhalb_der_aufnahme_nur_der_vorlauf_ring(rec):
    for v in range(1, 11):                     # 100 Frames anbieten, der Ring haelt 50
        rec._callback(_block(v), 10, None, None)
    assert not rec.is_recording and rec._buf == []
    assert rec._preroll_frames == 50
    assert [float(b[0]) for b in rec._preroll] == [6.0, 7.0, 8.0, 9.0, 10.0]


def test_start_uebernimmt_den_vorlauf(rec):
    for v in range(1, 11):
        rec._callback(_block(v), 10, None, None)
    rec.start()
    assert rec.is_recording and rec._frames == 50 and rec.elapsed_seconds == 0.5
    assert rec.captured_frames == 0                         # erst ab start() gezaehlt
    rec._callback(_block(99.0), 10, None, None)
    assert rec.captured_frames == 10
    arr = rec.stop()
    assert arr.dtype == np.float32 and len(arr) == 60
    assert arr[0] == 6.0 and arr[-1] == 99.0                # aeltester Block verdraengt, Aufnahme hinten
    assert not rec.is_recording and isinstance(rec._stream, _DummyStream)   # Stream bleibt offen
    assert not rec._stream.gestoppt


def test_nach_stop_wieder_nur_vorlauf(rec):
    rec.start()
    rec._callback(_block(1.0), 10, None, None)
    rec.stop()
    rec._callback(_block(2.0), 10, None, None)
    assert rec._buf == [] and rec._preroll_frames == 10
    assert len(rec.stop()) == 0                              # nicht in Aufnahme: leer


def test_mehrkanal_nimmt_den_ersten_kanal(rec):
    rec.start()
    stereo = np.column_stack([np.full(10, 1.0), np.full(10, 2.0)]).astype(np.float32)
    rec._callback(stereo, 10, None, None)
    assert rec.stop().tolist() == [1.0] * 10


def test_limit_wird_gemeldet_und_nichts_mehr_gespeichert():
    r = audio.Recorder(samplerate=100, persistent=True, preroll_s=0, max_seconds=1)
    r._stream = _DummyStream()
    r.start()
    for _ in range(12):
        r._callback(_block(1.0), 10, None, None)
    assert r.limit_hit and r._frames == 100
    assert len(r.stop()) == 100


def test_ohne_stream_keine_aufnahme():
    r = audio.Recorder(samplerate=100, persistent=False)
    assert not r.is_recording and len(r.stop()) == 0


def test_close_schliesst_den_stream(rec):
    stream = rec._stream
    rec.start()
    rec.close()
    assert stream.gestoppt and stream.geschlossen and rec._stream is None and not rec.is_recording


# --- Recorder: drain_until_silence -------------------------------------------------------------
def _aufnahme(teile: list[np.ndarray]) -> tuple[audio.Recorder, np.ndarray]:
    """Recorder in Aufnahme, gefuettert in 0,1-s-Bloecken wie vom Mikrofon."""
    r = audio.Recorder(samplerate=SR, persistent=True, preroll_s=0)
    r._stream = _DummyStream()
    r.start()
    ganz = np.concatenate(teile)
    for i in range(0, len(ganz), SR // 10):
        blk = ganz[i:i + SR // 10].reshape(-1, 1)
        r._callback(blk, len(blk), None, None)
    return r, ganz


def test_abholen_erst_ab_min_seconds(signal):
    r, ganz = _aufnahme([signal.sprache(10), signal.stille(0.8), signal.sprache(8)])
    assert r.buffered_seconds() == pytest.approx(18.8)
    assert r.drain_until_silence(min_seconds=25) is None
    assert r.buffered_seconds() == pytest.approx(18.8)


def test_abholen_bis_zur_pause_ohne_audio_zu_verlieren(signal):
    r, ganz = _aufnahme([signal.sprache(10), signal.stille(0.8), signal.sprache(8)])
    kopf = r.drain_until_silence(min_seconds=5)
    assert kopf is not None and 10.0 < len(kopf) / SR < 10.8
    rest = r.stop()
    assert np.array_equal(np.concatenate([kopf, rest]), ganz)   # nichts verloren, nichts doppelt


def test_ohne_pause_bleibt_alles_im_puffer(signal):
    r, ganz = _aufnahme([signal.sprache(12)])
    assert r.drain_until_silence(min_seconds=5) is None
    assert np.array_equal(r.stop(), ganz)


def test_abschnitt_bleibt_klein_letzte_pause_im_fenster(signal):
    """Bei grossem Puffer nur bis zur letzten Pause in den ersten max_chunk_s abholen, auch wenn
    dahinter noch eine Pause kommt (Pausen bei 5-6 s, 11-12 s, 18-19 s; Fenster 15 s)."""
    r, ganz = _aufnahme([signal.sprache(5), signal.stille(1), signal.sprache(5), signal.stille(1),
                         signal.sprache(6), signal.stille(1), signal.sprache(6)])
    kopf = r.drain_until_silence(min_seconds=5, max_chunk_s=15)
    assert 11.0 < len(kopf) / SR < 12.0
    assert np.array_equal(np.concatenate([kopf, r.stop()]), ganz)


def test_keine_pause_im_fenster_dann_im_ganzen_puffer(signal):
    r, ganz = _aufnahme([signal.sprache(12), signal.stille(1), signal.sprache(5)])
    kopf = r.drain_until_silence(min_seconds=5, max_chunk_s=8)
    assert 12.0 < len(kopf) / SR < 13.0
    assert np.array_equal(np.concatenate([kopf, r.stop()]), ganz)


def test_nach_stop_wird_nichts_mehr_abgeholt(signal):
    r, _ = _aufnahme([signal.sprache(10), signal.stille(1), signal.sprache(10)])
    r.stop()
    assert r.drain_until_silence(min_seconds=0) is None
