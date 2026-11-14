import json
import os

import pytest

from engine import cloud

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "samples")


def test_a_job_must_be_authorised_and_have_links():
    assert cloud.validate({"links": ["x"]}) and cloud.validate({"authorized": True})
    assert cloud.validate({"links": ["x"], "authorized": True}) == []
    assert cloud.validate({"links": ["x"] * 41, "authorized": True})
    with pytest.raises(SystemExit):
        cloud.run({"links": ["x"]}, "ignored")


def test_a_job_builds_video_thumbnails_title_and_description_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("SENORA_CONTACT_EMAIL", "ops@example.com")
    job = {"name": "Cloud Test", "authorized": True, "offline": True, "no_llm": True, "preview": True,
           "links": [f"{SAMPLES}/tone1.wav", f"{SAMPLES}/tone2.wav"],
           "settings": {"mood": "slow, calm", "channel": "Senora", "disc": "plain", "background": {"mode": "sky", "color": "night"},
                        "thumbs_selected": [{"family": "night", "variant": "blue"}, {"family": "swirl", "variant": "mono"}]}}
    out = tmp_path / "out"
    s = cloud.run(job, str(out), str(tmp_path / "work"))
    names = set(os.listdir(out))
    assert {"cloud-test.mp4", "cloud-test.thumbnail.jpg", "cloud-test.thumbnail-A.jpg", "cloud-test.thumbnail-B.jpg",
            "cloud-test.description.txt", "cloud-test.titles.txt", "summary.json"} <= names
    desc = (out / "cloud-test.description.txt").read_text()
    assert "Contact: ops@example.com" in desc and "Welcome to Senora." in desc          # e-mail came from the environment, not the job
    assert s["title"].startswith("[Playlist] ") and len(s["songs"]) == 2 and json.load(open(out / "summary.json"))["files"]
