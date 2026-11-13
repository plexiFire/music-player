import subprocess
from engine.media import audio, trim
from engine.playlist import importer


def _song(path, parts):
    """parts: [(seconds, freq_hz, volume)] -> wav; freq 0 = digital silence. Tones are 'music', volume sets loudness."""
    ins, fl = [], []
    for i, (sec, f, vol) in enumerate(parts):
        src = f"anullsrc=r=44100:cl=mono" if f == 0 else f"sine=frequency={f}:sample_rate=44100"
        ins += ["-f", "lavfi", "-t", str(sec), "-i", src]
        fl.append(f"[{i}:a]volume={vol * 8}[a{i}]")   # lavfi sine peaks at 0.125, so x8 = full-scale x vol
    graph = ";".join(fl) + ";" + "".join(f"[a{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", graph, path], check=True)
    return path


def _detect(path):
    return trim.detect(path, audio.probe(path)["duration"])


def test_trailing_and_leading_silence_are_cut(tmp_path):
    r = _detect(_song(str(tmp_path / "a.wav"), [(3, 0, 1), (20, 440, 0.5), (4, 0, 1)]))
    assert 2.5 < r["start"] < 3.2 and 22.8 < r["end"] < 23.6
    assert any("silence" in x for x in r["reasons"])


def test_quiet_extra_after_a_fade_to_silence_is_cut(tmp_path):
    # song (40s) -> 3s digital silence -> 8s of other audio (the "spoken outro")
    r = _detect(_song(str(tmp_path / "b.wav"), [(40, 440, 0.5), (3, 0, 1), (8, 300, 0.1)]))
    assert 39.8 < r["end"] < 40.6 and r["start"] == 0
    assert any("extra after the song" in x for x in r["reasons"])


def test_extra_before_the_song_is_cut(tmp_path):
    r = _detect(_song(str(tmp_path / "c.wav"), [(8, 300, 0.1), (3, 0, 1), (40, 440, 0.5)]))
    assert 10.5 < r["start"] < 11.4 and any("before the song" in x for x in r["reasons"])


def test_quiet_intro_and_continuous_song_are_left_alone(tmp_path):
    # soft intro (but not silent) then the song, no gaps: nothing to cut
    r = _detect(_song(str(tmp_path / "d.wav"), [(6, 440, 0.02), (25, 440, 0.5)]))
    assert r["reasons"] == [] and r["start"] == 0


def test_long_second_half_after_a_pause_is_not_treated_as_an_extra(tmp_path):
    # 15s song, 2s pause, 40s more music: too long to be an "extra" (> 25% / 45s rule) -> keep it all
    r = _detect(_song(str(tmp_path / "e.wav"), [(15, 440, 0.5), (2, 0, 1), (40, 440, 0.5)]))
    assert r["end"] > 56


def test_importer_trims_and_records_it(tmp_path):
    src = _song(str(tmp_path / "Band - Tune.wav"), [(40, 440, 0.5), (3, 0, 1), (8, 300, 0.1)])
    kw = dict(audio_dir=str(tmp_path / "a"), workdir=str(tmp_path / "w"), lookup=False, authorized=True)
    (t,) = importer.import_one(src, trim=True, **kw)
    assert 39.5 < t["duration"] < 41.0 and t["trim"]["removed"] > 9 and t["trim"]["reasons"]
    (u,) = importer.import_one(src, **{**kw, "audio_dir": str(tmp_path / "b")})   # default: NO trimming
    assert u["duration"] > 50 and "trim" not in u
