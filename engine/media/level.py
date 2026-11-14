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
