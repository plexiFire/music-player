import subprocess

import numpy as np

from engine.media import audio


def ff(*a):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True)


def peaks(path, secs=1.0):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True).stdout
    a = np.abs(np.frombuffer(raw, np.int16).astype(np.float32)) / 32768
    n = int(8000 * secs)
    return np.array([a[i:i + n].max() for i in range(0, len(a) - n + 1, n)])


def song(tmp_path):
    """30 s: 20 s of quiet tone, then 10 s of a loud one, so a damaged ending is impossible to miss."""
    ff("-f", "lavfi", "-i", "sine=frequency=300:duration=20", "-af", "volume=0.3", str(tmp_path / "a.wav"))
    ff("-f", "lavfi", "-i", "sine=frequency=500:duration=10", "-af", "volume=6", str(tmp_path / "b.wav"))
    ff("-i", str(tmp_path / "a.wav"), "-i", str(tmp_path / "b.wav"), "-filter_complex", "[0][1]concat=n=2:v=0:a=1", str(tmp_path / "song.wav"))
    return str(tmp_path / "song.wav")


def test_cutting_from_the_start_never_touches_the_end_of_the_song(tmp_path):
    src = song(tmp_path)
    ref = peaks(src)[12:]                                                    # the original from 0:12 on
    out = audio.process(src, str(tmp_path / "o"), name="cut", fmt="mp3", start=12.0, end=30.0)      # end = the real end of the song
    got = peaks(out)
    assert abs(len(got) - len(ref)) <= 1 and got[-8:].min() > 0.5 * ref[-8:].min()      # the loud ending is all still there
    assert np.abs(ref[:len(got)][:-1] - got[:len(ref)][:-1]).max() < 0.15               # and the whole kept part matches the original
    only_start = audio.process(src, str(tmp_path / "o"), name="cut2", fmt="mp3", start=12.0)
    assert peaks(only_start)[-8:].min() > 0.5 * ref[-8:].min()


def test_a_cut_at_the_end_still_fades_out_the_last_half_second_and_a_real_end_is_left_alone(tmp_path):
    src = song(tmp_path)
    cut = audio.process(src, str(tmp_path / "o"), name="e1", fmt="mp3", start=2.0, end=25.0)
    fine = peaks(cut, 0.25)
    assert abs(audio.probe(cut)["duration"] - 23.0) < 0.2 and fine[-1] < 0.5 * fine[-6]   # faded out at the new end
    untouched = audio.process(src, str(tmp_path / "o"), name="e2", fmt="mp3", start=2.0, end=30.0)
    fine = peaks(untouched, 0.25)
    assert fine[-1] > 0.8 * fine[-6]                                                       # the song's own ending is not faded by us


def test_no_cut_at_all_still_copies_the_whole_song(tmp_path):
    src = song(tmp_path)
    out = audio.process(src, str(tmp_path / "o"), name="whole", fmt="mp3")
    assert abs(audio.probe(out)["duration"] - 30.0) < 0.2
