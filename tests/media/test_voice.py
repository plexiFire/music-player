import shutil
import subprocess

import pytest

from engine.media import voice


def ff(*a):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True, timeout=60)


def make_song(tmp_path, tail):
    """40 s of 'music' (three tones with a beat) that fades out, 2 s of silence, then the tail clip."""
    ff("-f", "lavfi", "-i", "sine=frequency=220:duration=40", "-f", "lavfi", "-i", "sine=frequency=277:duration=40",
       "-f", "lavfi", "-i", "sine=frequency=330:duration=40", "-filter_complex",
       "amix=inputs=3,volume=6,afade=t=out:st=36:d=4,aresample=44100,aformat=channel_layouts=mono", str(tmp_path / "m.wav"))
    ff("-f", "lavfi", "-t", "2", "-i", "anullsrc=r=44100:cl=mono", str(tmp_path / "s.wav"))
    ff("-i", str(tmp_path / "m.wav"), "-i", str(tmp_path / "s.wav"), "-i", tail, "-filter_complex",
       "[2:a]aresample=44100,aformat=channel_layouts=mono[t];[0][1][t]concat=n=3:v=0:a=1[o]", "-map", "[o]", str(tmp_path / "song.wav"))
    return str(tmp_path / "song.wav")


def test_talking_like_sound_after_the_music_is_found_and_a_second_song_is_not(tmp_path):
    # talking-like: noisy consonant-heavy sound switching on and off at the rhythm of syllables
    ff("-f", "lavfi", "-i", "anoisesrc=d=14:c=white:a=0.5", "-af", "lowpass=f=5000,volume='0.4*(0.5+0.5*sin(2*PI*4*t))^2':eval=frame", str(tmp_path / "talk.wav"))
    found = voice.find(make_song(tmp_path, str(tmp_path / "talk.wav")))
    assert found and found[0]["where"] == "end" and 41 <= found[0]["start"] <= 46 and "looks like spoken words" in found[0]["reason"]
    # a hidden second song (steady tones, long) must not be called talking
    ff("-f", "lavfi", "-i", "sine=frequency=262:duration=40", "-af", "volume=3", str(tmp_path / "tune.wav"))
    assert voice.find(make_song(tmp_path, str(tmp_path / "tune.wav"))) == []


@pytest.mark.skipif(shutil.which("say") is None, reason="needs the macOS 'say' voice")
def test_a_real_synthetic_voice_after_the_song_is_found(tmp_path):
    subprocess.run(["say", "-o", str(tmp_path / "v.aiff"), "Thank you so much for listening. Please like and subscribe, see you in the next video."], check=True)
    found = voice.find(make_song(tmp_path, str(tmp_path / "v.aiff")))
    assert found and found[0]["where"] == "end"


def test_a_plain_song_with_no_extras_is_never_flagged(tmp_path):
    ff("-f", "lavfi", "-i", "sine=frequency=330:duration=60", "-af", "volume=5,afade=t=out:st=55:d=5", str(tmp_path / "plain.wav"))
    assert voice.find(str(tmp_path / "plain.wav")) == []
