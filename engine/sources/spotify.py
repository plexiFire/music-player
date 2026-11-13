"""Spotify Web API metadata (client-credentials flow). METADATA ONLY: Spotify audio is never downloaded.

Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET (free app at developer.spotify.com).
"""
import base64
import os
import re
import time

import requests

API = "https://api.spotify.com/v1"
TOKEN_URL = "https://accounts.spotify.com/api/token"
_token = {"value": None, "exp": 0}


class SpotifyError(RuntimeError):
    pass


def parse(link):
    """'https://open.spotify.com/(intl-xx/)track/ID?...' or 'spotify:track:ID' -> (kind, id) or None."""
    m = re.search(r"open\.spotify\.com/(?:intl-[a-z]+/)?(track|album|playlist)/([A-Za-z0-9]+)", link)
    m = m or re.match(r"spotify:(track|album|playlist):([A-Za-z0-9]+)", link.strip())
    return (m.group(1), m.group(2)) if m else None


def is_spotify(link):
    return parse(link) is not None


def _auth():
    if _token["value"] and time.time() < _token["exp"] - 30:
        return _token["value"]
    cid, sec = os.environ.get("SPOTIFY_CLIENT_ID"), os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not (cid and sec):
        raise SpotifyError("set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to use Spotify links")
    basic = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    r = requests.post(TOKEN_URL, data={"grant_type": "client_credentials"},
                      headers={"Authorization": f"Basic {basic}"}, timeout=15)
    if r.status_code != 200:
        raise SpotifyError(f"Spotify auth failed ({r.status_code}): check client id/secret")
    j = r.json()
    _token.update(value=j["access_token"], exp=time.time() + j.get("expires_in", 3600))
    return _token["value"]


def _get(url, **params):
    r = requests.get(url if url.startswith("http") else API + url, params=params,
                     headers={"Authorization": f"Bearer {_auth()}"}, timeout=15)
    if r.status_code == 404:
        raise SpotifyError("Spotify item not found (private or invalid link)")
    if r.status_code != 200:
        raise SpotifyError(f"Spotify API error {r.status_code}")
    return r.json()


def _norm(t, album=None):
    album = album or t.get("album") or {}
    imgs = sorted(album.get("images") or [], key=lambda i: -(i.get("width") or 0))
    return {"title": t["name"], "artist": ", ".join(a["name"] for a in t.get("artists", [])),
            "album": album.get("name", ""), "duration": (t.get("duration_ms") or 0) / 1000,
            "cover_url": imgs[0]["url"] if imgs else None, "isrc": (t.get("external_ids") or {}).get("isrc"),
            "source_link": (t.get("external_urls") or {}).get("spotify", ""), "source": "spotify"}


def tracks(link):
    """Return a list of normalised metadata dicts for a Spotify track/album/playlist link."""
    p = parse(link)
    if not p:
        raise SpotifyError(f"not a Spotify link: {link}")
    kind, sid = p
    if kind == "track":
        return [_norm(_get(f"/tracks/{sid}"))]
    if kind == "album":
        a = _get(f"/albums/{sid}")
        out, page = [], a["tracks"]
        while page:
            out += [_norm(t, a) for t in page["items"]]
            page = _get(page["next"]) if page.get("next") else None
        return out
    out, page = [], _get(f"/playlists/{sid}/tracks", limit=100)
    while page:
        out += [_norm(i["track"]) for i in page["items"] if i.get("track") and i["track"].get("name")]
        page = _get(page["next"]) if page.get("next") else None
    return out
