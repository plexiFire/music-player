import json
import os
import subprocess

import pytest

from engine.video import render

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "samples")


def _project(disc):
    return {"title": "t", "theme": "t", "disc": disc, "tracks": [
        {"title": "A", "artist": "x", "audio": f"{SAMPLES}/tone1.wav", "cover": f"{SAMPLES}/cover1.png"},
        {"title": "B", "artist": "y", "audio": f"{SAMPLES}/tone2.wav", "cover": f"{SAMPLES}/cover2.png"}]}


@pytest.mark.parametrize("disc", ["cd", "art"])
def test_render_with_other_disc_styles(tmp_path, disc):
    out = str(tmp_path / f"{disc}.mp4")
    res = render.render(_project(disc), out, preview=True, work_dir=str(tmp_path))
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                         "csv=p=0", out]).decode())
    assert abs(dur - res["duration"]) < 0.5 and os.path.getsize(out) > 50_000


def test_render_with_constant_background(tmp_path):
    proj = {**_project("cd"), "background": {"mode": "solid", "color": "blue"}}
    out = str(tmp_path / "solid.mp4")
    res = render.render(proj, out, preview=True, work_dir=str(tmp_path))
    assert os.path.getsize(out) > 50_000 and res["style"]["mode"] == "solid"


def test_a_stall_at_the_very_end_is_stopped_cleanly_and_accepted():
    import sys
    # fake 'ffmpeg': reports it reached 10 s, then hangs forever (python exits on SIGINT)
    code = "import sys,time;sys.stderr.write('frame=1 time=00:00:10.00 \\n');sys.stderr.flush();time.sleep(600)"
    render.run_ffmpeg([sys.executable, "-c", code], expect_seconds=10, is_complete=lambda: True, stall_end=2)


def test_a_stall_at_the_end_with_an_incomplete_file_is_an_error():
    import subprocess
    import sys
    code = "import sys,time;sys.stderr.write('time=00:00:10.00 \\n');sys.stderr.flush();time.sleep(600)"
    with pytest.raises(subprocess.CalledProcessError):
        render.run_ffmpeg([sys.executable, "-c", code], expect_seconds=10, is_complete=lambda: False, stall_end=2)


def test_a_normal_run_and_a_real_failure_behave_normally():
    import subprocess
    import sys
    render.run_ffmpeg([sys.executable, "-c", "pass"], expect_seconds=5, is_complete=lambda: False)
    with pytest.raises(subprocess.CalledProcessError):
        render.run_ffmpeg([sys.executable, "-c", "import sys;sys.exit(3)"], expect_seconds=5, is_complete=lambda: True)
