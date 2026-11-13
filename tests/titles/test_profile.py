import os

from engine.titles import profile

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "samples")


def test_moods_come_from_the_measured_sound():
    assert profile.moods_from_features([{"bpm": 80, "energy_db": -24, "brightness": 0.3}])[:2] == ["slow", "calm"]
    assert "upbeat" in profile.moods_from_features([{"bpm": 140, "energy_db": -10, "brightness": 0.5}])
    assert profile.moods_from_features([{}]) == []


def test_genres_come_from_youtube_tags_only_as_whole_words():
    tracks = [{"web_tags": ["indie pop", "music"]}, {"web_tags": ["pop", "popular"]}, {"web_tags": ["rapid"]}]
    assert profile.genres_from_tags(tracks)[0] in ("pop", "indie pop")
    assert "rap" not in profile.genres_from_tags(tracks)         # 'rapid' is not rap


def test_audio_features_on_a_real_file_do_not_crash():
    f = profile.audio_features(os.path.join(SAMPLES, "tone1.wav"))
    assert f == {} or {"bpm", "energy_db", "brightness"} <= set(f)       # sample may be too short to measure


def test_hashtags_use_detected_words_and_only_matching_search_phrases():
    prof = {"moods": ["sad", "late night"], "genres": ["indie pop"]}
    tags = profile.hashtags(prof, ["sad playlist", "sad songs for a drive", "sad indie pop songs"])
    assert "sadplaylist" in tags and "sadsongs" in tags
    assert all(t.isalnum() and t == t.lower() for t in tags)
    assert not any("drive" in t for t in tags)                          # 'drive' was never detected: not claimed


def test_build_works_without_network_or_llm(tmp_path):
    p = profile.build([{"title": "A", "artist": "X", "audio": os.path.join(SAMPLES, "tone1.wav"), "web_tags": ["indie"]}],
                      online=False, use_llm=False)
    assert p["genres"] == ["indie"] and p["hashtags"]
