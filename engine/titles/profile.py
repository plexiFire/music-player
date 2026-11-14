"""Work out what a playlist IS (genre + mood) from its songs, then derive hashtags from that and from what people search.

No input from the user needed:
  1. audio features (tempo, energy, brightness) are measured from the sound itself (ffmpeg + numpy)
  2. YouTube's own tags/category for each source video are collected at import time
  3. Groq (optional) names the genre/mood of the songs from artist + title + the measured features
  4. everything is merged into a profile: {genres, moods, mood, query, hashtags, features, source}
"""
import json
import re
import subprocess

import numpy as np
import requests

from . import hashtags as _tags, llm, research

SR = 11025
GENRE_WORDS = {"pop": "pop", "indie": "indie", "indie pop": "indie pop", "rock": "rock", "alternative": "alternative",
               "r&b": "r&b", "rnb": "r&b", "hip hop": "hip hop", "rap": "rap", "jazz": "jazz", "lofi": "lofi", "lo-fi": "lofi",
               "folk": "folk", "country": "country", "soul": "soul", "electronic": "electronic", "edm": "edm",
               "acoustic": "acoustic", "classical": "classical", "bollywood": "bollywood", "hindi": "hindi",
               "k-pop": "k-pop", "kpop": "k-pop", "metal": "metal", "blues": "blues", "reggae": "reggae", "latin": "latin"}


def audio_features(path, seconds=75):
    """Tempo (BPM), energy (dBFS RMS) and brightness (0..1) from the middle of the song. Never raises: {} on failure."""
    try:
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                   capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip() or 0)
        start = max(0.0, dur / 2 - seconds / 2)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.1f}", "-t", str(seconds), "-i", path, "-ac", "1",
                              "-ar", str(SR), "-f", "s16le", "-"], capture_output=True, stdin=subprocess.DEVNULL).stdout
        x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
        if len(x) < SR * 10:
            return {}
        rms = float(np.sqrt(np.mean(x ** 2)) + 1e-9)
        hop = 256
        n = (len(x) - 1024) // hop
        frames = np.stack([x[i * hop:i * hop + 1024] * np.hanning(1024) for i in range(n)])
        spec = np.abs(np.fft.rfft(frames, axis=1))
        freqs = np.fft.rfftfreq(1024, 1 / SR)
        centroid = float((spec * freqs).sum() / (spec.sum() + 1e-9))
        flux = np.maximum(0, np.diff(spec, axis=0)).sum(axis=1)                 # onset strength over time
        flux = flux - np.convolve(flux, np.ones(20) / 20, mode="same")
        ac = np.correlate(flux, flux, "full")[len(flux) - 1:]
        fps = SR / hop
        lo, hi = int(fps * 60 / 180), int(fps * 60 / 60)                        # 60..180 BPM
        lag = lo + int(np.argmax(ac[lo:hi]))
        bpm = 60 * fps / lag
        while bpm < 70:                                                         # fold half/double-time errors
            bpm *= 2
        while bpm > 160:
            bpm /= 2
        return {"bpm": round(bpm), "energy_db": round(20 * np.log10(rms), 1), "brightness": round(min(1.0, centroid / 4000), 2)}
    except Exception:
        return {}


def moods_from_features(feats):
    """Plain-word moods from measured sound. feats: list of audio_features dicts."""
    f = [x for x in feats if x]
    if not f:
        return []
    bpm = float(np.median([x["bpm"] for x in f]))
    en = float(np.median([x["energy_db"] for x in f]))
    br = float(np.median([x["brightness"] for x in f]))
    out = []
    if bpm < 100 and en < -18:
        out += ["slow", "calm"]
    elif bpm < 100:
        out += ["slow", "emotional"]
    elif bpm < 125:
        out += ["mellow"] if en < -18 else ["feel good"]
    else:
        out += ["upbeat", "energetic"]
    if br < 0.22:
        out.append("dark" if en < -20 else "warm")
    return out


def genres_from_tags(tracks):
    seen = {}
    for t in tracks:
        for tag in t.get("web_tags", []):
            for key, g in GENRE_WORDS.items():
                if re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", tag):
                    seen[g] = seen.get(g, 0) + 1
    return [g for g, _ in sorted(seen.items(), key=lambda kv: -kv[1])][:2]


def ask_groq(tracks, feats):
    """Ask Groq what genre/mood these songs are. Returns ({genres, moods}, warning)."""
    key = llm._env("GROQ_API_KEY")
    if not key:
        return {}, None
    songs = "; ".join(f"{t['title']} - {t['artist']}" if t.get("artist") else t["title"] for t in tracks[:12])
    f = [x for x in feats if x]
    sound = (f"Measured from the audio: median tempo {int(np.median([x['bpm'] for x in f]))} BPM, "
             f"median loudness {np.median([x['energy_db'] for x in f]):.0f} dBFS." if f else "")
    prompt = (f"These songs are on one YouTube playlist: {songs}. {sound}\n"
              "Say what genre and mood the playlist is. Use only words a listener would search for. "
              'Reply with JSON only: {"genres": ["1 or 2 genres, e.g. indie pop"], "moods": ["2 or 3 moods, e.g. sad, late night"]}')
    try:
        r = requests.post(llm.URL, headers={"Authorization": f"Bearer {key}"}, timeout=40, json={
            "model": llm._env("GROQ_MODEL") or llm.DEFAULT_MODEL, "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}]})
        if r.status_code != 200:
            return {}, f"Groq could not classify the songs ({r.status_code})"
        m = re.search(r"\{.*\}", r.json()["choices"][0]["message"]["content"], re.S)
        j = json.loads(m.group(0))
        clean = lambda xs: [re.sub(r"[^a-z0-9&' -]", "", str(x).lower()).strip() for x in xs if str(x).strip()][:3]
        return {"genres": clean(j.get("genres", [])), "moods": clean(j.get("moods", []))}, None
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as e:
        return {}, f"Groq could not classify the songs ({type(e).__name__})"


def hashtags(profile, suggestions=()):
    """Hashtags from the detected genre/mood, plus phrases people really type into YouTube search."""
    tags = []
    words = profile["moods"][:2] + profile["genres"][:1]
    for w in words:
        w = re.sub(r"[^a-z0-9]", "", w)
        if w:
            tags += [w + "playlist", w + "songs"]
    tags += ["playlist", "newmusic"]
    allowed = set(re.findall(r"[a-z0-9]+", " ".join(words + ["playlist", "songs", "music", "vibes"])))
    for s in suggestions:                     # real search phrases: "sad indie playlist" -> #sadindieplaylist
        ws = re.findall(r"[a-z0-9]+", s.lower())
        if 2 <= len(ws) <= 4 and all(w in allowed for w in ws):
            tags.append("".join(ws))
    out = []
    for t in dict.fromkeys(tags):
        if 4 <= len(t) <= 30:
            out.append(t)
    return out[:8]


def tag_pool(prof):
    """Hashtags used by the top YouTube videos for this playlist's mood/genre (kept in the profile, so no network later)."""
    m = (prof.get("moods") or [""])[0]
    g = prof.get("genre", "")
    queries = list(dict.fromkeys(q for q in (f"{m} {g} playlist".strip(), f"{g} playlist" if g else f"{m} songs playlist") if q.strip()))
    try:
        return _tags.research_pool(queries[:2])
    except Exception:
        return []


def build(tracks, online=True, use_llm=True):
    """The whole analysis. Returns the profile dict (and keeps per-song features inside it)."""
    feats = [audio_features(t["audio"]) if t.get("audio") else {} for t in tracks]
    moods = moods_from_features(feats)
    genres = genres_from_tags(tracks)
    warn, source = None, ["audio"] + (["youtube tags"] if genres else [])
    if use_llm:
        got, warn = ask_groq(tracks, feats)
        if got.get("genres") or got.get("moods"):
            genres = list(dict.fromkeys(got.get("genres", []) + genres))[:2]
            moods = list(dict.fromkeys(got.get("moods", [])[:2] + moods))[:3]
            source.append("groq")
    mood = ", ".join(moods[:2])                  # genre is kept apart so '[Playlist] Chill Songs for Pop' can't happen
    query = " ".join(([moods[0]] if moods else []) + genres[:1] + ["playlist"])
    prof = {"genres": genres, "genre": genres[0] if genres else "", "moods": moods, "mood": mood, "query": query, "features": feats, "source": source,
            "warning": warn}
    prof["hashtags"] = hashtags(prof, research.autocomplete(query) if online and mood else [])
    prof["tag_pool"] = tag_pool(prof) if online and mood else []
    return prof
