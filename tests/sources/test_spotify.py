import pytest
from engine.sources import spotify


def test_spotify_requires_credentials(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    spotify._token.update(value=None, exp=0)
    with pytest.raises(spotify.SpotifyError):
        spotify.tracks("https://open.spotify.com/track/abc")
