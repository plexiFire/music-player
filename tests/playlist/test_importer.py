import functools, http.server, json, os, subprocess, threading
import pytest
from engine.playlist import importer
from engine.sources import spotify, ytdlp
from engine.media import tags
from helpers import tone as _tone


def test_local_file_requires_attestation_then_imports(tmp_path):
    src = _tone(str(tmp_path / "Test Artist - Test Song.wav"))
    kw = dict(audio_dir=str(tmp_path / "a"), workdir=str(tmp_path / "w"), lookup=False)
    with pytest.raises(ytdlp.NotAuthorized):
        importer.import_one(src, **kw)
    (t,) = importer.import_one(src, authorized=True, **kw)
    assert t["audio"].endswith(".mp3") and os.path.exists(t["cover"]) and t["rights"]["basis"] == "user-attested"
    assert tags.read(t["audio"])["duration"] > 1.5


def test_web_url_end_to_end_via_ytdlp(tmp_path):
    """Real yt-dlp download from a local HTTP server hosting a generated tone (authorized by attestation)."""
    srv = tmp_path / "srv"; srv.mkdir()
    _tone(str(srv / "Tone Maker - Sine Song.mp3"))
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(srv))
    h.log_message = lambda *a, **k: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/Tone%20Maker%20-%20Sine%20Song.mp3"
    kw = dict(audio_dir=str(tmp_path / "a"), workdir=str(tmp_path / "w"), lookup=False, fmt="m4a")
    try:
        with pytest.raises(ytdlp.NotAuthorized):  # no licence, no attestation -> refused, nothing downloaded
            importer.import_one(url, **kw)
        assert not os.path.exists(tmp_path / "w" / "_dl")
        (t,) = importer.import_one(url, authorized=True, **kw)
    finally:
        httpd.shutdown()
    assert (t["title"], t["artist"]) == ("Sine Song", "Tone Maker")
    assert t["audio"].endswith(".m4a") and abs(t["duration"] - 2) < 0.3
    proj = importer.add_to_project(str(tmp_path / "p.json"), [t], title="T")
    assert json.load(open(tmp_path / "p.json"))["tracks"][0]["audio"] == t["audio"] == proj["tracks"][0]["audio"]


def test_spotify_metadata_then_authorized_local_audio(tmp_path, monkeypatch):
    assert spotify.parse("https://open.spotify.com/intl-de/track/4uLU6hMCjMI75M1A2tKUQC?si=x") == ("track", "4uLU6hMCjMI75M1A2tKUQC")
    assert spotify.parse("spotify:album:abc123") == ("album", "abc123")
    monkeypatch.setattr(spotify, "_get", lambda url, **p: {
        "name": "Sine Song", "artists": [{"name": "Tone Maker"}], "duration_ms": 2000,
        "album": {"name": "Tones", "images": [{"url": "http://x/s.jpg", "width": 64}, {"url": "http://x/b.jpg", "width": 640}]},
        "external_ids": {"isrc": "X1"}, "external_urls": {"spotify": "https://open.spotify.com/track/abc"}})
    lib = tmp_path / "lib"; lib.mkdir()
    _tone(str(lib / "Tone Maker - Sine Song.wav"))
    link = "https://open.spotify.com/track/abc"
    kw = dict(audio_dir=str(tmp_path / "a"), workdir=str(tmp_path / "w"), lookup=False, library_dir=str(lib))
    monkeypatch.setattr(importer.metadata, "download_cover", lambda u, p: (_ for _ in ()).throw(OSError()))
    (t,) = importer.import_one(link, authorized=True, **kw)
    assert t["artist"] == "Tone Maker" and t["album"] == "Tones" and t["audio"] and t["source_link"] == link
    # no matching audio -> metadata kept, flagged, never fetched from Spotify
    (m,) = importer.import_one(link, authorized=True, **{**kw, "library_dir": str(tmp_path)})
    assert m["audio"] is None and m["needs_audio"]


def test_import_handles_webm_that_mutagen_cannot_read(tmp_path):
    src = str(tmp_path / "Some Artist - Some Song.webm")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=duration=2", "-c:a", "libopus", src],
                   check=True)
    (t,) = importer.import_one(src, str(tmp_path / "a"), str(tmp_path / "w"), authorized=True, lookup=False)
    assert t["audio"].endswith(".mp3") and t["duration"] > 1.5


def test_second_import_does_not_overwrite_earlier_covers(tmp_path):
    from engine import cli
    wd, proj = str(tmp_path / "w"), str(tmp_path / "p.json")
    for n in ("A - One", "B - Two"):
        src = _tone(str(tmp_path / f"{n}.wav"))
        cli.main(["import", src, "--authorized", "--offline", "--audio-dir", str(tmp_path / "a"),
                  "--workdir", wd, "--project", proj])
    covers = [t["cover"] for t in json.load(open(proj))["tracks"]]
    assert len(covers) == 2 and len(set(covers)) == 2
