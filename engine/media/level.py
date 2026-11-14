"""Even out the volume between songs. Measures each song's loudness (EBU R128, in LUFS) and, only if you choose it,
applies ONE plain gain per song (no compression, so the song keeps its own dynamics) with a peak limiter as a safety.
Nothing is changed unless asked: the original files are never touched, leveled copies are separate files."""
import os
import re
import subprocess

TARGET = -14.0          # LUFS: where YouTube plays most music
MAX_GAIN = 12.0         # never push or pull a song by more than this many dB


def measure(path):
    """Integrated loudness in LUFS (e.g. -9.8 loud, -17 quiet). None if it can't be measured."""
    r = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", path, "-filter_complex", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    m = re.findall(r"\bI:\s*(-?[\d.]+)\s*LUFS", r.stderr)
    return float(m[-1]) if m else None


def gain_for(lufs, target=TARGET):
    if lufs is None:
        return 0.0
    return round(max(-MAX_GAIN, min(MAX_GAIN, target - lufs)), 1)


def _af(gain_db):
    return f"volume={gain_db}dB,alimiter=limit=0.97:level=disabled"


def apply(src, dst, gain_db):
    """Write a copy of src with the gain applied (mp3, same sample rate)."""
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-af", _af(gain_db), "-c:a", "libmp3lame", "-q:a", "2", dst],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError("could not even out the volume: " + (r.stderr.strip().splitlines() or ["unknown error"])[-1])
    return dst


def demo_clip(a, b, gain_a, gain_b, dst, secs=8):
    """The end of song a followed by the start of song b, so you can hear the jump between them (with the gains, or with 0, 0)."""
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    dur_a = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a],
                                 capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip() or secs)
    start = max(0.0, dur_a - secs - 1.0)               # a little before the end, so the fade-out is included
    g = (f"[0:a]atrim=start={start:.2f}:duration={secs},asetpts=PTS-STARTPTS,aresample=44100,{_af(gain_a)}[x];"
         f"[1:a]atrim=duration={secs},asetpts=PTS-STARTPTS,aresample=44100,{_af(gain_b)}[y];[x][y]concat=n=2:v=0:a=1[o]")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", a, "-i", b, "-filter_complex", g, "-map", "[o]",
                        "-c:a", "libmp3lame", "-q:a", "4", dst], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError("could not build the listening clip")
    return dst


# ================= per-boundary leveling and the loudness graph =================
# Modes: "off"; "whole" = every song goes to the same level (one gain per song, as above);
#        "pairs" = only the boundaries you pick: the END of song i and the START of song i+1 are each moved half way toward the
#        other (so neither changes much); the change is held for HOLD seconds, then fades back to 0 dB over RAMP seconds. The middle of a song is untouched.
import math

HOLD = 4.0            # a start/end adjustment is held in full for this many seconds (= the part that is compared) ...
RAMP = 4.0            # ... and then fades back to nothing over this many seconds
EDGE_SECS = HOLD      # how much of the end of a song / start of the next one is compared
WINDOW = 0.5          # the loudness graph has one point every half second
SILENCE_DB = -60.0


def curve(path):
    """Loudness (RMS, dB) every 0.5 s of the song: the graph. Digital silence becomes -90."""
    from . import trim
    return [round(max(-90.0, x), 1) for x in trim.levels(path)]


def edge_level(db, side, secs=EDGE_SECS):
    """Average loudness (dB, power average) of the last or first `secs` seconds, ignoring digital silence. None if nothing is audible."""
    n = max(1, int(min(secs, max(WINDOW, len(db) * WINDOW / 3)) / WINDOW))
    part = db[-n:] if side == "end" else db[:n]
    vals = [10 ** (x / 10) for x in part if x > SILENCE_DB]
    return round(10 * math.log10(sum(vals) / len(vals)), 1) if vals else None


def boundary_jumps(curves):
    """For each neighbouring pair: {i, end_db, start_db, jump} where jump = end of song i minus start of song i+1 (dB, + = the next one starts quieter)."""
    out = []
    for i in range(len(curves) - 1):
        e, s = edge_level(curves[i], "end"), edge_level(curves[i + 1], "start")
        out.append({"i": i + 1, "end_db": e, "start_db": s, "jump": None if e is None or s is None else round(e - s, 1)})
    return out


def plan_gains(lufs, curves, mode, pairs=(), target=TARGET):
    """One dict per song: {"whole": dB for the whole song, "start": dB at its very start, "end": dB at its very end}."""
    n = len(curves)
    plan = [{"whole": 0.0, "start": 0.0, "end": 0.0} for _ in range(n)]
    if mode == "whole":
        for i in range(n):
            plan[i]["whole"] = gain_for(lufs[i] if i < len(lufs) else None, target)
    elif mode == "pairs":
        jumps = {j["i"]: j["jump"] for j in boundary_jumps(curves)}
        for i in pairs:
            d = jumps.get(i)
            if d is None or not 1 <= i < n:
                continue
            d = max(-MAX_GAIN * 2, min(MAX_GAIN * 2, d))
            plan[i - 1]["end"] += round(-d / 2, 1)         # end of song i moves toward the next one
            plan[i]["start"] += round(d / 2, 1)            # start of song i+1 moves toward the previous one
    return plan


def _fade(x, hold=HOLD, ramp=RAMP):
    """1 for the first `hold` seconds from an edge, then down to 0 over `ramp` seconds."""
    return min(1.0, max(0.0, 1 - (x - hold) / ramp))


def gain_at(p, t, duration):
    """The gain (dB) this plan applies to a song at time t. The same formula is written for ffmpeg in expr()."""
    return p["whole"] + p["start"] * _fade(t) + p["end"] * _fade(duration - t)


def expr(p, duration, hold=HOLD, ramp=RAMP):
    """volume expression for ffmpeg (linear factor from the same dB formula as gain_at)."""
    f = lambda x: f"min(1,max(0,1-({x}-{hold})/{ramp}))"
    return f"pow(10,({p['whole']}+{p['start']}*{f('t')}+{p['end']}*{f(f'({duration:.3f}-t)')})/20)"


def predict(db, p, duration):
    """The loudness graph AFTER the plan, worked out from the measured graph (no audio is rendered)."""
    return [round(x + gain_at(p, i * WINDOW + WINDOW / 2, duration), 1) if x > SILENCE_DB else x for i, x in enumerate(db)]


def _plan_af(p, duration):
    return f"volume='{expr(p, duration)}':eval=frame,alimiter=limit=0.97:level=disabled"


def is_neutral(p):
    return abs(p["whole"]) < 0.05 and abs(p["start"]) < 0.05 and abs(p["end"]) < 0.05


def apply_plan(src, dst, p, duration):
    """Write a copy of src with the plan applied (the original is never touched)."""
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-af", _plan_af(p, duration), "-c:a", "libmp3lame", "-q:a", "2", dst],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError("could not even out the volume: " + (r.stderr.strip().splitlines() or ["unknown error"])[-1])
    return dst


def demo_clip_plan(a, b, plan_a, plan_b, dur_a, dur_b, dst, secs=10):
    """The last `secs` seconds of song a followed by the first `secs` seconds of song b, with the plans applied (or neutral plans for 'before')."""
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    secs = max(3, min(secs, int(dur_a) - 1, int(dur_b) - 1))
    g = (f"[0:a]{_plan_af(plan_a, dur_a)},atrim=start={max(0.0, dur_a - secs):.3f},asetpts=PTS-STARTPTS,aresample=44100[x];"
         f"[1:a]{_plan_af(plan_b, dur_b)},atrim=duration={secs},asetpts=PTS-STARTPTS,aresample=44100[y];[x][y]concat=n=2:v=0:a=1[o]")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", a, "-i", b, "-filter_complex", g, "-map", "[o]", "-c:a", "libmp3lame", "-q:a", "4", dst],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError("could not build the listening clip: " + (r.stderr.strip().splitlines() or ["unknown error"])[-1])
    return dst


def loud_key(path):
    """Changes whenever the audio file changes (a cut, a restore), so a stale loudness graph is never used."""
    try:
        st = os.stat(path)
        return f"{path}|{st.st_mtime_ns}|{st.st_size}"
    except OSError:
        return None


def loudness_of(track):
    """{"key", "lufs", "db"} for a track: the cached numbers if they still belong to the file, else measured now."""
    key = loud_key(track["audio"])
    c = track.get("loud")
    if c and c.get("key") == key and c.get("db"):
        return c
    return {"key": key, "lufs": measure(track["audio"]), "db": curve(track["audio"])}


def settings_of(project):
    """('off'|'whole'|'pairs', [boundary numbers]) from a project; the older single on/off switch means 'whole'."""
    mode = project.get("level_mode") or ("whole" if project.get("level_audio") else "off")
    return (mode if mode in ("off", "whole", "pairs") else "off"), sorted({int(i) for i in project.get("level_pairs", []) if str(i).lstrip("-").isdigit()})
