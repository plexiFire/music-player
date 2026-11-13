import json
import pytest
from engine.titles import generate, history, llm, pipeline as suggest, research, score

PROJECT = {"title": "Late Night", "theme": "late night playlist", "title_style": "any", "tracks": [
    {"title": "Sailor Song", "artist": "Gigi Perez"}, {"title": "Self Aware", "artist": "Temper City"},
    {"title": "Riptide", "artist": "Vance Joy"}]}
VIDEOS = [{"title": "Late Night R&B Playlist | SZA, Daniel Caesar", "views": 6_000_000, "duration": 3000, "channel": "a"},
          {"title": "late night vibes playlist for studying", "views": 5_000_000, "duration": 3000, "channel": "b"},
          {"title": "Chill late night drive playlist", "views": 100, "duration": 3000, "channel": "c"}]


@pytest.fixture
def offline_research(monkeypatch):
    monkeypatch.setattr(research, "search", lambda q, n=25: VIDEOS)
    monkeypatch.setattr(research, "autocomplete", lambda q: ["late night playlist", "late night playlist to study",
                                                              "late night playlist r&b"])


def test_research_patterns_weight_by_views():
    p = research.analyse(VIDEOS, "late night playlist")
    assert "studying" in p["keywords"] and p["pct_pipe"] >= 30 and "late" not in p["keywords"]


def test_titles_are_relevant_ranked_and_explained(offline_research):
    res = suggest.suggest(PROJECT, n=8, use_llm=False)
    assert 3 <= len(res["titles"]) <= 8
    scores = [c["score"] for c in res["titles"]]
    assert scores == sorted(scores, reverse=True)
    for c in res["titles"]:
        assert c["reasons"] and len(c["title"]) <= 100
        assert {"late", "night"} & set(c["title"].lower().split()) or any(a in c["title"] for a in ("Gigi", "Temper", "Vance"))


def test_irrelevant_clickbait_and_overlong_titles_are_rejected():
    ctx = suggest.context(PROJECT)
    assert score.score("Best Pizza Recipes Ever", ctx)[0] == 0
    assert score.score("Late Night Playlist you won't believe", ctx)[0] == 0
    assert score.score("Late Night Playlist " + "x" * 90, ctx)[0] == 0


def test_a_second_playlist_does_not_repeat_the_first(offline_research, tmp_path):
    h = str(tmp_path / "h.json")
    first = {c["title"] for c in suggest.suggest(PROJECT, n=8, use_llm=False, history_path=h)["titles"]}
    second = {c["title"] for c in suggest.suggest(PROJECT, n=8, use_llm=False, history_path=h)["titles"]}
    assert first and second and not (first & second)
    assert all(history.similarity(a, b) <= 0.7 for a in first for b in second)


def test_groq_titles_are_used_and_scored_like_any_other(offline_research, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    class R:
        status_code = 200
        def json(self): return {"choices": [{"message": {"content": json.dumps({"titles": [
            "Late Night Playlist: Gigi Perez, Vance Joy & More for Quiet Hours", "Totally Unrelated Cooking Show"]})}}]}
    seen = {}
    def fake_post(url, **kw): seen.update(kw); return R()
    monkeypatch.setattr(llm.requests, "post", fake_post)
    res = suggest.suggest(PROJECT, n=10, use_llm=True)
    srcs = {c["title"]: c["source"] for c in res["titles"]}
    assert srcs["Late Night Playlist: Gigi Perez, Vance Joy & More for Quiet Hours"] == "groq"
    assert "Totally Unrelated Cooking Show" not in srcs          # irrelevant LLM output is filtered out
    assert "Gigi Perez" in seen["json"]["messages"][1]["content"]  # prompt carries the real tracklist


def test_missing_groq_key_degrades_to_templates(offline_research, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(llm, "ENV_FILE", "/nonexistent/.env")      # ignore the developer's real .env
    res = suggest.suggest(PROJECT, n=5, use_llm=True)
    assert res["titles"] and any("GROQ_API_KEY" in w for w in res["warnings"])


def test_llm_parse_tolerates_messy_replies():
    assert llm.parse('Sure! {"titles": ["A long enough title here", " Another   title "]}') == ["A long enough title here", "Another title"]
    assert llm.parse("garbage") == []


def test_titles_never_borrow_artists_languages_or_genres_from_research(offline_research, monkeypatch):
    monkeypatch.setattr(research, "autocomplete", lambda q: ["late night playlist", "late night playlist hindi",
                                                              "late night playlist r&b", "late night playlist sad"])
    monkeypatch.setattr(research, "search", lambda q, n=25: VIDEOS + [
        {"title": "Late Night Bollywood Drake SZA Playlist", "views": 9_000_000, "duration": 1, "channel": "x"}])
    res = suggest.suggest(PROJECT, n=12, use_llm=False)
    text = " ".join(c["title"].lower() for c in res["titles"])
    for bad in ("hindi", "r&b", "bollywood", "drake", "sza", "caesar"):
        assert bad not in text
    assert "sad" in text or "playlist" in text      # neutral demand words are still used


def test_theme_word_playlist_is_not_doubled(offline_research):
    res = suggest.suggest(PROJECT, n=12, use_llm=False)
    assert not any("playlist playlist" in c["title"].lower() for c in res["titles"])


def test_stated_mood_overrides_borrowed_moods_and_openings_vary(offline_research, monkeypatch):
    monkeypatch.setattr(research, "autocomplete", lambda q: ["late night playlist", "late night playlist romantic",
                                                              "late night playlist sad", "late night playlist chill"])
    res = suggest.suggest(PROJECT, n=10, mood="sad", use_llm=False)
    text = " ".join(c["title"].lower() for c in res["titles"])
    assert "romantic" not in text and "chill" not in text
    openings = [" ".join(c["title"].lower().split()[:4]) for c in res["titles"]]
    assert max(openings.count(o) for o in openings) <= 2


def test_groq_key_can_come_from_dotenv_file(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("# c\nGROQ_API_KEY='abc123'\n")
    monkeypatch.setattr(llm, "ENV_FILE", str(env))
    assert llm._env("GROQ_API_KEY") == "abc123" and llm.available()
    env.write_text("GROQ_API_KEY=\n")
    assert not llm.available()


def test_groq_json_mode_rejection_retries_in_plain_mode(offline_research, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    calls = []
    class Bad:
        status_code = 400
        text = '{"error":{"message":"Failed to validate JSON","failed_generation":"..."}}'
    class Good:
        status_code = 200
        def json(self): return {"choices": [{"message": {"content": 'Here: {"titles": ["Late Night Playlist for Quiet Hours | Gigi Perez"]}'}}]}
    def fake_post(url, **kw):
        calls.append("response_format" in kw["json"])
        return Bad() if kw["json"].get("response_format") else Good()
    monkeypatch.setattr(llm.requests, "post", fake_post)
    res = suggest.suggest(PROJECT, n=10, use_llm=True)
    assert calls == [True, False]
    assert any(c["source"] == "groq" for c in res["titles"])


def test_mood_gives_bracket_style_titles(offline_research):
    proj = {**PROJECT, "title": "Playlist 5", "theme": "Playlist 5", "mood": "slow evening", "title_style": "bracket"}
    res = suggest.suggest(proj, n=6, use_llm=False)
    titles = [c["title"] for c in res["titles"]]
    assert titles[0].startswith("[Playlist]") and "slow evening" in titles[0].lower()
    assert any(t == "[Playlist] Songs for a slow evening" for t in titles)
    assert not any("5 Playlist" in t for t in titles)


def test_adjective_mood_reads_naturally(offline_research):
    proj = {**PROJECT, "mood": "sad", "title_style": "bracket"}
    titles = [c["title"] for c in suggest.suggest(proj, n=6, use_llm=False)["titles"]]
    assert any(t.startswith("[Playlist] Sad Songs") or "feel sad" in t for t in titles)
    assert not any("for a sad" in t.lower() for t in titles)


def test_mood_phrase():
    from engine.titles.generate import mood_phrase
    assert mood_phrase("slow evening") == "Songs for a slow evening"
    assert mood_phrase("sad, late night") == "Sad songs"
    assert mood_phrase("") == ""


def test_research_searches_the_mood_not_the_playlist_name(monkeypatch):
    asked = []
    monkeypatch.setattr(research, "search", lambda q, n=25: asked.append(q) or [])
    monkeypatch.setattr(research, "autocomplete", lambda q: [])
    suggest.suggest({**PROJECT, "title": "1234", "theme": "1234", "mood": "slow evening"}, n=5, use_llm=False, online=True)
    assert asked == ["slow evening playlist"]


def test_no_mood_and_a_meaningless_name_gives_a_hint_not_junk(offline_research):
    res = suggest.suggest({**PROJECT, "title": "1234", "theme": "1234", "mood": ""}, n=5, use_llm=False)
    assert res["titles"] == [] and "mood" in res["warnings"][0].lower()


def test_groq_key_is_found_through_senora_env(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(llm, "ENV_FILE", "/nonexistent/.env")
    f = tmp_path / "keys.env"
    f.write_text("GROQ_API_KEY=abc\n")
    monkeypatch.setenv("SENORA_ENV", str(f))
    assert llm.available()


def test_bracket_titles_that_repeat_playlist_or_stuff_artists_rank_lower():
    from engine.titles import score as sc
    ctx = {**suggest.context({**PROJECT, "mood": "slow evening", "title_style": "bracket"}), "mood": "slow evening"}
    good, _ = sc.score("[Playlist] Songs for a Slow Evening", ctx)
    dup, _ = sc.score("[Playlist] Slow Evening Playlist Songs", ctx)
    stuffed, _ = sc.score("[Playlist] Slow Evening with Gigi Perez, Temper City & Vance Joy", ctx)
    assert good > dup and good > stuffed


def test_a_title_may_not_claim_a_genre_the_playlist_never_stated():
    from engine.titles import score as sc
    ctx = {**suggest.context({**PROJECT, "mood": "slow evening"}), "mood": "slow evening"}
    assert sc.score("[Playlist] Slow Evening Acoustic Vibes", ctx)[0] == 0
    assert sc.score("[Playlist] Slow Evening Sunset with Gigi Perez", ctx)[0] == 0   # 'sunset' is not the stated mood
    assert sc.score("[Playlist] Sailor Song by Gigi Perez and Dusk Till Dawn", {**ctx, "track_titles": ["Sailor Song", "Dusk Till Dawn"], "mood": "slow evening"})[0] > 0   # a song's own name may contain such words
    assert sc.score("[Playlist] Slow Evening Indie Songs", ctx)[0] == 0
    assert sc.score("[Playlist] Songs for a Slow Evening", ctx)[0] > 0
    ctx2 = {**ctx, "mood": "acoustic evening"}                       # stated by the user: allowed
    assert sc.score("[Playlist] Acoustic Songs for an Evening", ctx2)[0] > 0
