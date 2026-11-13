import os, tempfile
from engine.sources import library


def test_library_matching():
    with tempfile.TemporaryDirectory() as d:
        for n in ("Gigi Perez - Sailor Song.mp3", "other.mp3", "notes.txt"):
            open(os.path.join(d, n), "w").close()
        assert library.find_audio(d, "Sailor Song", "Gigi Perez").endswith("Sailor Song.mp3")
        assert library.find_audio(d, "Unknown Track") is None
