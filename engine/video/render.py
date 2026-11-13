"""Build and run the FFmpeg graph: looping background + spinning vinyl + per-track cover."""
import json
import os
import subprocess
import tempfile
from PIL import Image

from ..look import background, coverbg, vinyl
from . import timestamps

FPS = 30


def probe_duration(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path])
    return float(json.loads(out)["format"]["duration"])


def _has_encoder(name):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL).stdout
    return name in out


def render(project, out_path, preview=False, fade=None, rotation_secs=None, work_dir=None):
    """Look options in project.json (all optional):
      "background": {"mode": "cover" (default: blurred cover art per track) | "marble", "darken": 0.3,
                     "bg_lead": 1.2 (seconds the new background starts fading in BEFORE the cover changes),
                     + marble fields: palette, scale, warp ...}
      "transition": "cut" (default) | "fade", "fade": seconds;  "fps": 30 | 60;  "stars": 3 (vinyl stickers)
      "spin_secs": 19.2 (seconds per vinyl turn; measured from the reference video, 33 rpm real-life = 1.8)
    """
    tracks = project["tracks"]
    rotation_secs = float(rotation_secs or project.get("spin_secs", 19.2))
    if fade is None:
        fade = float(project.get("fade", 0.6)) if project.get("transition", "cut") == "fade" else 0.0
    FPS = int(project.get("fps", 30))
    W, H = (1280, 720) if preview else (1920, 1080)
    k = H / 1080
    work = work_dir or tempfile.mkdtemp(prefix="senora_")
    durs = [probe_duration(t["audio"]) for t in tracks]
    starts, ts_text = timestamps.build(tracks, durs)
    total = sum(durs)
    n = len(tracks)
    bgopt = dict(project.get("background", {}))
    mode = bgopt.pop("mode", "cover")

    # layout: cover left of centre, vinyl peeking out behind on the right
    s = int(584 * k) // 2 * 2
    cover_x = int((W - 1.44 * s) / 2)
    cover_y = (H - s) // 2
    vin_d = int(s * 0.9) // 2 * 2
    vin_cx = cover_x + int(s * 0.99)
    vin_cy = H // 2
    vin = vinyl.make_vinyl(os.path.join(work, "vinyl.png"), diameter=vin_d, stars=int(project.get("stars", 3)),
                           label=(228, 220, 200))
    covers = []
    for i, t in enumerate(tracks):
        p = os.path.join(work, f"cover{i}.png")
        Image.open(t["cover"]).convert("RGB").resize((s, s), Image.LANCZOS).save(p)
        covers.append(p)

    # ---- inputs: [backgrounds...] vinyl covers... audio...
    cmd = ["ffmpeg", "-y", "-v", "error", "-stats"]
    lead = float(bgopt.get("bg_lead", 1.2))
    f = []
    if mode == "marble":
        style = {**background.style_from_seed(project.get("title", "playlist")), **bgopt}
        bg = os.path.join(work, "bg.mp4")
        background.make_loop(bg, style=style, final=(W, H))
        cmd += ["-stream_loop", "-1", "-i", bg]
        f.append(f"[0:v]fps={FPS},format=yuv420p[base]")
        nbg, thumb_src, thumb_at = 1, bg, 5.0
    else:
        bgs = [coverbg.make(t["cover"], os.path.join(work, f"bg{i}.png"), (W, H),
                            darken=float(bgopt.get("darken", 0.3))) for i, t in enumerate(tracks)]
        for p in bgs:
            cmd += ["-loop", "1", "-framerate", str(FPS), "-i", p]
        nbg, thumb_src, thumb_at = n, bgs[0], 0.0
        for i in range(n):  # slow drift across the oversized image, different phase per track
            f.append(f"[{i}:v]crop={W}:{H}:x='(iw-{W})/2*(1+0.85*sin(2*PI*t/38+{i * 1.7:.2f}))':"
                     f"y='(ih-{H})/2*(1+0.85*cos(2*PI*t/46+{i * 2.3:.2f}))',format=yuv420p[bg{i}]")
        f.append(f"[bg0]null[base]")
    cmd += ["-loop", "1", "-framerate", str(FPS), "-i", vin]
    for p in covers:
        cmd += ["-loop", "1", "-framerate", str(FPS), "-i", p]
    for t in tracks:
        cmd += ["-i", t["audio"]]
    vi, ci, ai = nbg, nbg + 1, nbg + 1 + n

    f.append(f"[{vi}:v]format=rgba,rotate=a=2*PI*t/{rotation_secs}:ow=iw:oh=ih:c=none[vin]")
    cur = "base"
    if mode != "marble":  # each next background fades in a little BEFORE its cover appears
        for i in range(1, n):
            st = max(0.0, starts[i] - lead)
            end = starts[i + 1] - lead if i < n - 1 else total
            hold = (starts[i + 1] if i < n - 1 else total)
            f.append(f"[bg{i}]format=rgba,fade=t=in:st={st:.3f}:d={starts[i] - st:.3f}:alpha=1[bgf{i}]")
            f.append(f"[{cur}][bgf{i}]overlay=enable='between(t,{st:.3f},{total:.3f})'[b{i}]")
            cur = f"b{i}"
    f.append(f"[{cur}][vin]overlay=x={vin_cx}-w/2:y={vin_cy}-h/2:shortest=0[v0]")
    cur = "v0"
    for i in range(n):
        st, en = starts[i], starts[i] + durs[i]
        fin = f"fade=t=in:st={st:.3f}:d={fade}:alpha=1," if (i > 0 and fade > 0) else ""
        hold = en + fade if (i < n - 1 and fade > 0) else en
        f.append(f"[{ci + i}:v]format=rgba,{fin}null[c{i}]")
        f.append(f"[{cur}][c{i}]overlay=x={cover_x}:y={cover_y}:enable='between(t,{st:.3f},{hold:.3f})'[v{i + 1}]")
        cur = f"v{i + 1}"
    a_in = "".join(f"[{ai + i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}];" for i in range(n))
    a_cat = "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[aout]"
    graph = ";".join(f) + ";" + a_in + a_cat
    if preview and _has_encoder("h264_videotoolbox"):      # macOS hardware encoder
        venc = ["-c:v", "h264_videotoolbox", "-b:v", "4M"]
    elif preview:                                          # Linux / cloud runners
        venc = ["-c:v", "libx264", "-crf", "24", "-preset", "veryfast"]
    else:
        venc = ["-c:v", "libx264", "-crf", "16", "-preset", "slow", "-profile:v", "high"]
    cmd += ["-filter_complex", graph, "-map", f"[{cur}]", "-map", "[aout]",
            "-t", f"{total:.3f}", *venc, "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", out_path]
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)  # never wait on the keyboard
    return {"bg": thumb_src, "thumb_at": thumb_at, "style": {"mode": mode, **bgopt}, "out": out_path,
            "duration": total, "timestamps": ts_text, "starts": starts}
