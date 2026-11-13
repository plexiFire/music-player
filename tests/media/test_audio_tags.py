import subprocess
import pytest
from engine.media import audio, tags
from helpers import tone as _tone


def test_ffmpeg_process_formats_and_normalize(tmp_path):
    src = _tone(str(tmp_path / "t.wav"))
    for fmt in ("mp3", "m4a", "flac"):
        out = audio.process(src, str(tmp_path / "o"), fmt=fmt, normalize=(fmt == "mp3"))
        p = audio.probe(out)
        assert out.endswith("." + fmt) and abs(p["duration"] - 2) < 0.2 and p["sample_rate"] == 48000


@pytest.mark.parametrize("fmt", ["mp3", "m4a", "flac", "wav"])
def test_mutagen_roundtrip_with_cover(tmp_path, fmt):
    out = audio.process(_tone(str(tmp_path / "t.wav")), str(tmp_path), name="x", fmt=fmt)
    from PIL import Image
    Image.new("RGB", (64, 64), "red").save(tmp_path / "c.jpg")
    tags.write(out, "Song", "Artist", "Album", cover=str(tmp_path / "c.jpg"), comment="hi")
    t = tags.read(out)
    assert (t["title"], t["artist"], t["album"]) == ("Song", "Artist", "Album")
    if fmt != "wav":
        from engine.playlist import folder
        assert folder._embedded_cover(out, str(tmp_path / "e.jpg"))
