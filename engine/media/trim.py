"""Auto-trim the non-music extras at the start/end of a track (silence, spoken intros/outros).

No speech recognition: it works from loudness only, so it is deliberately conservative.
  * leading / trailing silence is cut;
  * a SHORT segment at the very start or end that sits behind a long silent gap AND is clearly quieter than the
    song (default >= 6 dB) is cut (e.g. a quiet voice-over after the song has faded out);
  * never cuts more than 25% of the track, and never touches the middle of the song.
Every decision comes back with a reason so you can review it.
"""
import re
import statistics
import subprocess

WIN = 0.5            # analysis window, seconds
EDGE_DB = -45.0      # edge windows below this count as silence (start / end of the file)
GAP_DB = -58.0       # a gap between the song and an "extra" must be near-digital silence (quiet intros stay safe)
GAP_MIN = 1.2        # ...for at least this long
LOUDER_OK = 3.0      # an extra louder than the song body (+3 dB) is probably music, not an extra
MAX_EXTRA = (45.0, 0.25)   # an extra can't be longer than 45 s or 25% of the track


def levels(path):
    """RMS level (dB) of each 0.5 s window of the track."""
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-af",
         "aresample=22050,asetnsamples=n=11025:p=0,astats=metadata=1:reset=1,"
         "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-", "-f", "null", "-"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL)
    out = []
    for m in re.finditer(r"RMS_level=(-?[\d.]+|-inf)", r.stdout):
        out.append(-120.0 if m.group(1) == "-inf" else float(m.group(1)))
    return out


def _runs(flags):
    """[(start_idx, end_idx_exclusive)] of consecutive True values."""
    runs, i = [], 0
    while i < len(flags):
        if flags[i]:
            j = i
            while j < len(flags) and flags[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


def analyse(lv, duration):
    """Return {"start", "end", "reasons"} in seconds. start=0/end=duration means nothing to cut."""
    n = len(lv)
    start, end, reasons = 0.0, duration, []
    loud = [x for x in lv if x > EDGE_DB]
    if n < 8 or not loud:
        return {"start": start, "end": end, "reasons": reasons}
    body = statistics.median(loud)
    limit = min(MAX_EXTRA[0], MAX_EXTRA[1] * duration)
    edge = _runs([x < EDGE_DB for x in lv])
    gaps = [(a, b) for a, b in _runs([x < GAP_DB for x in lv]) if (b - a) * WIN >= GAP_MIN]

    def extra_ok(a, b):   # windows a..b-1: short, and not louder than the song itself?
        seg = [x for x in lv[a:b] if x > GAP_DB]
        return 0 < (b - a) * WIN <= limit and bool(seg) and statistics.median(seg) <= body + LOUDER_OK

    # ---- end: trailing silence, then an extra hiding behind a silent gap
    if edge and edge[-1][1] == n and (n - edge[-1][0]) * WIN >= 1.0:
        end = min(duration, edge[-1][0] * WIN + 0.3)
        reasons.append(f"trailing silence ({duration - end:.1f}s)")
    tail_gaps = [g for g in gaps if g[1] < n and g[0] * WIN < end]
    if tail_gaps and extra_ok(tail_gaps[-1][1], min(n, int(end / WIN))):
        a, b = tail_gaps[-1]
        cut = a * WIN + 0.2
        reasons.append(f"extra after the song: {end - cut:.1f}s of audio after a fade to silence "
                       f"(song ends ~{cut:.0f}s) - REVIEW")
        end = cut
    # ---- start: leading silence, then an extra before a silent gap
    if edge and edge[0][0] == 0 and edge[0][1] * WIN >= 1.0:
        start = max(0.0, edge[0][1] * WIN - 0.2)
        reasons.append(f"leading silence ({start:.1f}s)")
    head_gaps = [g for g in gaps if g[0] > 0 and g[1] * WIN > start]
    if head_gaps and extra_ok(int(start / WIN), head_gaps[0][0]):
        a, b = head_gaps[0]
        cut = b * WIN - 0.2
        reasons.append(f"extra before the song: {cut - start:.1f}s of audio before a silent gap - REVIEW")
        start = cut
    if (start + (duration - end)) > 0.25 * duration:     # safety: something is off, don't cut
        return {"start": 0.0, "end": duration, "reasons": ["skipped: would remove >25% of the track"]}
    return {"start": round(start, 2), "end": round(end, 2), "reasons": reasons}


def detect(path, duration):
    return analyse(levels(path), duration)
