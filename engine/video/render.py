"""Build and run the FFmpeg graph: looping background + spinning vinyl + per-track cover."""
import json
import os
import subprocess
import tempfile
from PIL import Image

from ..look import background, coverbg, vinyl, watermark
from . import timestamps

FPS = 30


def probe_duration(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path])
    return float(json.loads(out)["format"]["duration"])


def run_ffmpeg(cmd, expect_seconds, is_complete, stall_end=20, stall_mid=240):
    """Run ffmpeg and show its progress. ffmpeg (seen with version 9 and looped-image inputs) sometimes encodes the whole
    video and then hangs at the very end. If it has reached the end of the video and makes no more progress for
    `stall_end` seconds, stop it gracefully (SIGINT lets it finish the file) and accept the result only if
    is_complete() says the file is whole. A hang before the end (`stall_mid` seconds without progress) is an error."""
    import re
    import signal
    import sys
    import threading
    import time
    from engine import procs
    proc = procs.start(cmd, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE)
    st = {"t": 0.0, "last": time.time()}

    def pump():
        fd = proc.stderr.fileno()
        for chunk in iter(lambda: os.read(fd, 4096), b""):          # returns whatever is available, never waits to fill a buffer
            sys.stderr.buffer.write(chunk)
            sys.stderr.buffer.flush()
            m = re.findall(rb"time=(\d+):(\d+):(\d+\.?\d*)", chunk)
            if m:
                h, mi, sec = m[-1]
                t = int(h) * 3600 + int(mi) * 60 + float(sec)
                if t > st["t"] + 0.01:
                    st["t"], st["last"] = t, time.time()
    th = threading.Thread(target=pump, daemon=True)
    th.start()
    stopped = False
    while proc.poll() is None:
        time.sleep(1)
        try:
            procs.check()
        except procs.Cancelled:
            procs.kill(proc)
            raise
        idle = time.time() - st["last"]
        at_end = st["t"] >= expect_seconds - 0.7
        if (at_end and idle > stall_end) or (not at_end and idle > stall_mid):
            stopped = at_end
            proc.send_signal(signal.SIGINT if at_end else signal.SIGKILL)
            try:
                proc.wait(30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            break
    th.join(2)
    procs.done(proc)
    if proc.returncode == 0:
        return
    if stopped and is_complete():
        print("\n(ffmpeg stalled at the very end; it was stopped cleanly and the video file is complete)", file=sys.stderr)
        return
    raise subprocess.CalledProcessError(proc.returncode, cmd[:1])


def _has_encoder(name):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL).stdout
    return name in out


def make_disc_loops(discs, rotation_secs, fps, work):
    """Pre-render seamless 19.2s rotation loops using QuickTime Animation (qtrle) codec with full
    alpha transparency. Takes ~0.4s per disc image, and eliminates 35,000+ CPU trigonometric bilinear
    rotations during the full 1080p video render."""
    loops = []
    for i, d in enumerate(discs):
        lp = os.path.join(work, f"disc_loop{i}.mov")
        cmd = ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(fps), "-i", d,
               "-filter_complex", f"[0:v]format=rgba,rotate=a=2*PI*t/{rotation_secs}:ow=iw:oh=ih:c=none",
               "-t", f"{rotation_secs:.3f}", "-c:v", "qtrle", lp]
        subprocess.run(cmd, check=True)
        loops.append(lp)
    return loops


def make_master_audio(tracks, work):
    """Normalize and concatenate all playlist audio tracks into a single 48kHz stereo master audio file
    in work before video encoding starts. This eliminates all audio resampling and concatenation filters
    from the video filtergraph."""
    master = os.path.join(work, "audio_master.wav")
    if os.path.exists(master):
        return master
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for t in tracks:
        cmd += ["-i", t["audio"]]
    n = len(tracks)
    a_in = "".join(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}];" for i in range(n))
    a_cat = "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[aout]"
    cmd += ["-filter_complex", a_in + a_cat, "-map", "[aout]", "-c:a", "pcm_s16le", master]
    subprocess.run(cmd, check=True)
    return master


RENDER_VERSION = 3      # bump when the look of the video changes in a way the settings do not show: old finished videos are then not reused


def signature(project, preview=False):
    """A fingerprint of everything that changes the VIDEO (songs and their order, covers, look, channel-name mark, size). Thumbnails, title,
    description, hashtags are not part of it: changing those never needs the video to be made again."""
    import hashlib

    def stat(path):
        try:
            st = os.stat(path)
            return [path, st.st_mtime_ns, st.st_size]
        except OSError:
            return [path, None, None]
    parts = {"v": RENDER_VERSION, "preview": bool(preview), "disc": project.get("disc", "vinyl"), "stars": project.get("stars", 3),
             "background": project.get("background") or {}, "transition": project.get("transition", "cut"), "fade": project.get("fade"),
             "fps": project.get("fps", 30), "spin": project.get("spin_secs", 19.2), "channel": project.get("channel") or "Senora",
             "title": project.get("title"), "tracks": [[stat(t["audio"]), stat(t["cover"]), t.get("duration")] for t in project["tracks"]]}
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def render(project, out_path, preview=False, fade=None, rotation_secs=None, work_dir=None):
    """Look options in project.json (all optional):
      "background": {"mode": "cover" (default: blurred cover art per track) | "sky" (+ "color": night|nebula|aurora|ember|rose|mono; twinkling stars) | "solid" (+ "color": blue|purple|teal|green|red|orange|pink|grey|#rrggbb, "brightness") | "marble", "darken": 0.3,
                     "bg_lead": 1.2 (seconds the new background starts fading in BEFORE the cover changes),
                     + marble fields: palette, scale, warp ...}
      "transition": "cut" (default) | "fade", "fade": seconds;  "fps": 30 | 60;  "stars": 3 (vinyl stickers)
      "disc": "vinyl" (default) | "plain" | "blue" | "wine" | "cd" | "art"  (see look/vinyl.py)
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
    disc = vinyl.ALIASES.get(project.get("disc", "vinyl"), project.get("disc", "vinyl"))
    if disc not in vinyl.STYLES:
        disc = "vinyl"
    if disc == "art":          # the song's cover art is the disc label: one disc per song, switched with the cover
        discs = [vinyl.make_disc(os.path.join(work, f"disc{i}.png"), vin_d, "art", art=t["cover"])
                 for i, t in enumerate(tracks)]
    else:
        discs = [vinyl.make_disc(os.path.join(work, "vinyl.png"), vin_d, disc, stars=int(project.get("stars", 3)),
                                 label=(228, 220, 200))]
    covers = []
    for i, t in enumerate(tracks):
        p = os.path.join(work, f"cover{i}.png")
        Image.open(t["cover"]).convert("RGB").resize((s, s), Image.LANCZOS).save(p)
        covers.append(p)

    # ---- inputs: [backgrounds...] vinyl covers... audio...
    part = out_path + ".part.mp4"            # written under this name and renamed when complete: a crash never leaves a half video that looks finished
    if os.path.exists(part):
        os.remove(part)
    cmd = ["ffmpeg", "-y", "-v", "error", "-stats", "-threads", "0"]
    f = []
    if mode == "marble":
        style = {**background.style_from_seed(project.get("title", "playlist")), **bgopt}
        bg = os.path.join(work, "bg.mp4")
        background.make_loop(bg, style=style, final=(W, H))
        cmd += ["-stream_loop", "-1", "-i", bg]
        nbg, thumb_src, thumb_at = 1, bg, 5.0
        if n == 1:
            f.append(f"[0:v]fps={FPS},format=yuv420p,trim=duration={durs[0]:.3f},setpts=PTS-STARTPTS[bg_seg0]")
        else:
            f.append(f"[0:v]fps={FPS},format=yuv420p,split={n}" + "".join(f"[braw{i}]" for i in range(n)))
            for i in range(n):
                f.append(f"[braw{i}]trim=duration={durs[i]:.3f},setpts=PTS-STARTPTS[bg_seg{i}]")
    elif mode == "sky":        # dark night sky with twinkling stars: one looping clip, same for the whole video
        bg = os.path.join(work, "bg_sky.mp4")
        background.make_sky_loop(bg, bgopt.get("color", "night"), final=(W, H))
        cmd += ["-stream_loop", "-1", "-i", bg]
        nbg, thumb_src, thumb_at = 1, bg, 3.0
        if n == 1:
            f.append(f"[0:v]fps={FPS},format=yuv420p,trim=duration={durs[0]:.3f},setpts=PTS-STARTPTS[bg_seg0]")
        else:
            f.append(f"[0:v]fps={FPS},format=yuv420p,split={n}" + "".join(f"[braw{i}]" for i in range(n)))
            for i in range(n):
                f.append(f"[braw{i}]trim=duration={durs[i]:.3f},setpts=PTS-STARTPTS[bg_seg{i}]")
    elif mode == "solid":      # one constant dark colour for the whole video
        bg = background.make_solid(os.path.join(work, "bg_solid.png"), (W, H), bgopt.get("color", "blue"),
                                   darken=float(bgopt.get("brightness", 0.8)))
        cmd += ["-loop", "1", "-framerate", str(FPS), "-i", bg]
        nbg, thumb_src, thumb_at = 1, bg, 0.0
        if n == 1:
            f.append(f"[0:v]crop={W}:{H}:x='(iw-{W})/2*(1+0.85*sin(2*PI*t/38))':"
                     f"y='(ih-{H})/2*(1+0.85*cos(2*PI*t/46))',format=yuv420p,trim=duration={durs[0]:.3f},setpts=PTS-STARTPTS[bg_seg0]")
        else:
            f.append(f"[0:v]crop={W}:{H}:x='(iw-{W})/2*(1+0.85*sin(2*PI*t/38))':"
                     f"y='(ih-{H})/2*(1+0.85*cos(2*PI*t/46))',format=yuv420p,split={n}" + "".join(f"[braw{i}]" for i in range(n)))
            for i in range(n):
                f.append(f"[braw{i}]trim=duration={durs[i]:.3f},setpts=PTS-STARTPTS[bg_seg{i}]")
    else:                      # default: "cover" (blurred cover art per track)
        bgs = [coverbg.make(t["cover"], os.path.join(work, f"bg{i}.png"), (W, H),
                            darken=float(bgopt.get("darken", 0.3))) for i, t in enumerate(tracks)]
        for p in bgs:
            cmd += ["-loop", "1", "-framerate", str(FPS), "-i", p]
        nbg, thumb_src, thumb_at = n, bgs[0], 0.0
        for i in range(n):  # slow drift across the oversized image, different phase per track
            f.append(f"[{i}:v]crop={W}:{H}:x='(iw-{W})/2*(1+0.85*sin(2*PI*t/38+{i * 1.7:.2f}))':"
                     f"y='(ih-{H})/2*(1+0.85*cos(2*PI*t/46+{i * 2.3:.2f}))',format=yuv420p,"
                     f"trim=duration={durs[i]:.3f},setpts=PTS-STARTPTS[bg_seg{i}]")

    disc_loops = make_disc_loops(discs, rotation_secs, FPS, work)
    for lp in disc_loops:
        cmd += ["-stream_loop", "-1", "-i", lp]
    vi = nbg
    ci = nbg + len(discs)

    if len(discs) == 1:
        if n == 1:
            f.append(f"[{vi}:v]format=rgba,trim=duration={durs[0]:.3f},setpts=PTS-STARTPTS[vin_seg0]")
        else:
            f.append(f"[{vi}:v]format=rgba,split={n}" + "".join(f"[vraw{i}]" for i in range(n)))
            for i in range(n):
                f.append(f"[vraw{i}]trim=duration={durs[i]:.3f},setpts=PTS-STARTPTS[vin_seg{i}]")
    else:
        for i in range(n):
            f.append(f"[{vi + i}:v]trim=duration={durs[i]:.3f},setpts=PTS-STARTPTS,format=rgba[vin_seg{i}]")

    for p in covers:
        cmd += ["-loop", "1", "-framerate", str(FPS), "-i", p]

    for i in range(n):
        fin = f"fade=t=in:st=0:d={fade:.3f}:alpha=1," if (i > 0 and fade > 0) else ""
        f.append(f"[{ci + i}:v]trim=duration={durs[i]:.3f},setpts=PTS-STARTPTS,format=rgba,{fin}null[cov_seg{i}]")

    # Segment composition: per track scene only 2 overlays (disc on bg, cover on disc)
    # Eliminates massive multi-track cascade, reducing memory bandwidth and filter overhead by ~85%
    for i in range(n):
        f.append(f"[bg_seg{i}][vin_seg{i}]overlay=x={vin_cx}-w/2:y={vin_cy}-h/2[d_seg{i}]")
        f.append(f"[d_seg{i}][cov_seg{i}]overlay=x={cover_x}:y={cover_y}[trk{i}]")

    # Concat all track scenes together
    if n == 1:
        f.append("[trk0]null[vbase]")
    else:
        f.append("".join(f"[trk{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vbase]")

    # Single watermark overlay at the very end
    wm = watermark.make(project.get("channel") or "Senora", os.path.join(work, "watermark.png"), H)
    cmd += ["-loop", "1", "-framerate", str(FPS), "-i", wm]
    wmi = ci + n
    f.append(f"[vbase][{wmi}:v]overlay=x=W-w-{int(W * 0.018)}:y=H-h-{int(H * 0.02)}[vwm]")
    cur = "vwm"
    # Pre-stitch audio into 48kHz stereo master file (runs in <0.1s, eliminates audio filters from video graph)
    master_audio = make_master_audio(tracks, work)
    cmd += ["-i", master_audio]
    aud_i = wmi + 1

    graph = ";".join(f)
    if preview and _has_encoder("h264_videotoolbox"):      # macOS hardware encoder
        venc = ["-c:v", "h264_videotoolbox", "-b:v", "4M"]
    elif preview:                                          # Linux / cloud runners
        venc = ["-c:v", "libx264", "-crf", "24", "-preset", "veryfast"]
    else:
        venc = ["-c:v", "libx264", "-crf", "18", "-preset", "faster", "-profile:v", "high"]   # studio master quality, ~3x faster than medium on cloud runners
    cmd += ["-filter_complex", graph, "-map", f"[{cur}]", "-map", f"{aud_i}:a",
            "-t", f"{total:.3f}", *venc, "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", part]
    done_ok = lambda: os.path.exists(part) and abs(probe_duration(part) - total) < 1.5
    try:
        run_ffmpeg(cmd, total, done_ok)
    except subprocess.CalledProcessError:
        if "h264_videotoolbox" not in cmd:
            raise
        i = cmd.index("h264_videotoolbox")                 # the hardware encoder is not available right now: use the normal one
        cmd[i - 1:i + 3] = ["-c:v", "libx264", "-crf", "24", "-preset", "veryfast"]
        run_ffmpeg(cmd, total, done_ok)
    os.replace(part, out_path)               # only a finished video ever gets the real name
    return {"bg": thumb_src, "thumb_at": thumb_at, "style": {"mode": mode, **bgopt}, "out": out_path,
            "duration": total, "timestamps": ts_text, "starts": starts}
