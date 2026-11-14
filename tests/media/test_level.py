import os
import subprocess

from engine.media import level

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "samples")


def test_gain_moves_toward_the_target_and_is_capped():
    assert level.gain_for(-20.0) == 6.0 and level.gain_for(-9.0) == -5.0
    assert level.gain_for(-40.0) == level.MAX_GAIN and level.gain_for(10.0) == -level.MAX_GAIN
    assert level.gain_for(None) == 0.0


def test_measure_apply_and_demo_clip_really_change_the_loudness(tmp_path):
    src = str(tmp_path / "loud.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=14", "-af", "volume=4", src], check=True)
    quiet = str(tmp_path / "quiet.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=14", "-af", "volume=1", quiet], check=True)
    a, b = level.measure(src), level.measure(quiet)
    assert a is not None and b is not None and a - b > 10                      # the two really differ a lot
    out = level.apply(quiet, str(tmp_path / "q2.mp3"), level.gain_for(b))
    assert abs(level.measure(out) - level.TARGET) < 1.5                         # one gain brings it to the target
    orig = level.demo_clip(src, quiet, 0, 0, str(tmp_path / "o.mp3"), secs=4)
    even = level.demo_clip(src, quiet, level.gain_for(a), level.gain_for(b), str(tmp_path / "e.mp3"), secs=4)
    assert os.path.getsize(orig) > 1000 and os.path.getsize(even) > 1000
    assert os.path.exists(src) and level.measure(src) == a                      # the original is never touched
