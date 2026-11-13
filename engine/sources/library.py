"""Match a track to an audio file in a folder by name similarity."""
import os
import re

AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus"}


def _tok(s):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def find_audio(directory, title, artist=""):
    want = _tok(f"{artist} {title}")
    best, best_score = None, 0.0
    for name in sorted(os.listdir(directory)):
        stem, ext = os.path.splitext(name)
        if ext.lower() not in AUDIO_EXT:
            continue
        have = _tok(stem)
        sc = len(want & have) / max(1, len(_tok(title)))
        if sc > best_score:
            best, best_score = os.path.join(directory, name), sc
    return best if best_score >= 0.6 else None
