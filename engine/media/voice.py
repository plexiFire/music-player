"""Spoken words at the start or end of a song (an outro where someone talks), found from the sound itself - no model, no network.

Per second of audio we measure (a) how strongly the loudness rises and falls at the rhythm of syllables (2-8 Hz) and
(b) the zero-crossing rate (consonants like 's' and 'f' make it high). Speech has both at once; music, even with singing,
rarely does for long. A stretch counts as speech only if it is long, almost all seconds agree, and it sits where talking
usually hides: after the music has faded out (end) or before the music starts (start).

This only RECOMMENDS. Nothing is ever cut automatically. Limits: it is a heuristic. Rap, spoken-word songs and
sung-through-silence can fool it; the page says 'looks like spoken words', never 'is'."""
import subprocess

import numpy as np

SR = 16000
MOD_MIN, ZCR_MIN = 0.50, 0.125      # per-second thresholds (measured on real outros vs. real songs)
MIN_RUN, MIN_DENSITY = 6, 0.80      # at least this many seconds, with this share of them speech-like


def _load(path, start, dur):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0, start):.2f}", "-t", f"{dur:.2f}", "-i", path, "-ac", "1",
                          "-ar", str(SR), "-f", "s16le", "-"], capture_output=True, stdin=subprocess.DEVNULL).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def per_second(x):
    """[(level_db, syllable_modulation 0..1, zero_crossing_rate)] for each whole second of x."""
    hop = SR // 100
    n = len(x) // hop
    if n < 100:
        return []
    env = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-10)
    out = []
    for s in range(n // 100):
        e = env[s * 100:(s + 1) * 100]
        ed = e - e.mean()
        sp = np.abs(np.fft.rfft(ed * np.hanning(len(ed)))) ** 2
        fr = np.fft.rfftfreq(len(ed), 0.01)
        band = sp[(fr >= 2) & (fr <= 8)].sum() / (sp[(fr >= 0.5) & (fr <= 25)].sum() + 1e-12)
        seg = x[s * SR:(s + 1) * SR]
        out.append((20 * np.log10(e.mean() + 1e-9), float(band), float(np.mean(np.abs(np.diff(np.sign(seg)))) / 2)))
    return out


def speechlike(sec):
    return [mod >= MOD_MIN and zcr >= ZCR_MIN and db > -50 for db, mod, zcr in sec]


def _best_run(flags, from_end=False):
    """The longest stretch (start_idx, end_idx_exclusive) that is mostly speech-like, trimmed to speech-like seconds at both ends."""
    best, n = None, len(flags)
    for i in range(n):
        if not flags[i]:
            continue
        for j in range(n, i + MIN_RUN - 1, -1):
            if sum(flags[i:j]) / (j - i) >= MIN_DENSITY and flags[j - 1]:
                if best is None or (j - i) > (best[1] - best[0]):
                    best = (i, j)
                break
    return best


def region_is_speech(sec):
    """After the music has ended the only things left are silence, talking, or a hidden track, so judge the whole stretch by
    its averages (talking has pauses, so a per-second test misses it): syllable rhythm, consonant noise, and how often both show."""
    if not 5 <= len(sec) <= 25:         # an outro of talking is short; a bonus track is long (and soft singing looks like talking)
        return False
    mod = np.array([m for _, m, _ in sec])
    zcr = np.array([z for _, _, z in sec])
    return bool(mod.mean() >= 0.52 and zcr.mean() >= 0.11 and np.mean(mod >= 0.4) >= 0.6 and np.mean(zcr >= 0.10) >= 0.5)


def find(path, duration=None):
    """-> list of {"where": "end"|"start", "start": s, "end": s, "seconds": n, "reason": str} for spoken-looking stretches."""
    if duration is None:
        duration = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                        capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip() or 0)
    found = []
    # END: after the music has faded out (a quiet gap), words follow
    t0 = max(0.0, duration - 60)
    sec = per_second(_load(path, t0, duration - t0))
    flags = speechlike(sec)
    for gap in range(len(sec)):
        if sec[gap][0] < -40:                                  # the music ended here (near silence)
            after = [x for x in sec[gap + 1:]]
            quiet_end = next((i for i, x in enumerate(after) if x[0] <= -50), len(after))     # the stretch that has sound in it
            region = after[:quiet_end]
            run = _best_run(flags[gap + 1:])
            if (run and run[1] - run[0] >= MIN_RUN) or region_is_speech(region):
                a = t0 + gap + 1 + (run[0] if run and run[1] - run[0] >= MIN_RUN else 0)
                b = t0 + gap + 1 + (run[1] if run and run[1] - run[0] >= MIN_RUN else len(region))
                found.append({"where": "end", "start": round(a, 1), "end": round(min(b, duration), 1), "seconds": round(b - a),
                              "reason": f"looks like spoken words after the song ends (about {round(b - a)}s, from {a:.0f}s)"})
                break
    # START: talking before the music comes in (the music is clearly louder than the talking)
    head = per_second(_load(path, 0, 45))
    hf = speechlike(head)
    run = _best_run(hf[:30])
    if run and run[0] <= 2 and run[1] - run[0] >= MIN_RUN and len(head) > run[1] + 3:
        talk = np.mean([d for d, _, _ in head[run[0]:run[1]]])
        music = np.mean([d for d, _, _ in head[run[1] + 1:run[1] + 6]])
        if music - talk >= 6:
            found.append({"where": "start", "start": float(run[0]), "end": float(run[1]), "seconds": run[1] - run[0],
                          "reason": f"looks like spoken words before the song starts (about {run[1] - run[0]}s)"})
    return found
