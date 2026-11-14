from engine.sources import ytdlp


def test_cookies_are_only_passed_when_the_file_exists(tmp_path, monkeypatch):
    monkeypatch.delenv("SENORA_YT_COOKIES_FILE", raising=False)
    assert "--cookies" not in ytdlp._ytdlp()
    monkeypatch.setenv("SENORA_YT_COOKIES_FILE", str(tmp_path / "missing.txt"))
    assert "--cookies" not in ytdlp._ytdlp()                       # set but no such file: ignored, no crash
    f = tmp_path / "c.txt"
    f.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("SENORA_YT_COOKIES_FILE", str(f))
    cmd = ytdlp._ytdlp()
    assert cmd[-2:] == ["--cookies", str(f)]


def test_research_and_hashtag_lookups_use_the_same_command():
    from engine.titles import hashtags, research
    assert research._ytdlp() == ytdlp._ytdlp() == hashtags._ytdlp()
