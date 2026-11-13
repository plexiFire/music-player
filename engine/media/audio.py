"""FFmpeg audio processing: probe, transcode to a standard format, optional loudness normalisation."""
import json
import os
import subprocess

# format -> (extension, ffmpeg codec args)
FORMATS = {
    "mp3": (".mp3", ["-c:a", "libmp3lame", "-b:a", "320k"]),
    "m4a": (".m4a", ["-c:a", "aac", "-b:a", "256k"]),
    "flac": (".flac", ["-c:a", "flac"]),
    "wav": (".wav", ["-c:a", "pcm_s16le"]),
}


def probe(path):
    """Return {duration, codec, sample_rate, channels, bit_rate} for an audio file."""
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name,sample_rate,channels,bit_rate:format=duration",
         "-of", "json", path])
    d = json.loads(out)
    s = (d.get("streams") or [{}])[0]
    if not s:
        raise ValueError(f"no audio stream in {path}")
    return {"duration": float(d["format"]["duration"]), "codec": s.get("codec_name"),
            "sample_rate": int(s.get("sample_rate", 0)), "channels": s.get("channels"),
            "bit_rate": int(s["bit_rate"]) if s.get("bit_rate") else None}


def process(src, dst_dir, name=None, fmt="mp3", normalize=False, start=0.0, end=None):
    """Transcode src to dst_dir/<name>.<fmt> (video/cover streams dropped, tags carried over).

    normalize=True applies EBU R128 loudness normalisation (-14 LUFS). Returns the output path.
    """
    if fmt not in FORMATS:
        raise ValueError(f"unsupported format {fmt!r}; choose from {sorted(FORMATS)}")
    ext, codec = FORMATS[fmt]
    os.makedirs(dst_dir, exist_ok=True)
    stem = name or os.path.splitext(os.path.basename(src))[0]
    dst = os.path.join(dst_dir, stem + ext)
    if os.path.abspath(dst) == os.path.abspath(src):
        raise ValueError("source and destination are the same file")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", src, "-vn", "-map", "0:a:0", "-map_metadata", "0"]
    af = []
    if start or end:                       # trim, with short fades so cuts never click
        if end:
            cmd += ["-to", f"{end:.3f}"]
        if start:
            cmd += ["-ss", f"{start:.3f}"]
            af.append("afade=t=in:d=0.1")
        if end:
            af.append(f"afade=t=out:st={max(0.0, end - start - 0.5):.3f}:d=0.5")
    if normalize:
        af.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    if af:
        cmd += ["-af", ",".join(af)]
    cmd += ["-ar", "48000", *codec, dst]
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)
    probe(dst)  # fail loudly if the output is not valid audio
    return dst
