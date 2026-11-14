from server import reconcile as R


def T(link, title="x", ok=True):
    return {"title": title, "from_link": link, "audio": "a.mp3" if ok else None, "error": None if ok else "boom"}


def test_the_same_video_has_one_key_whatever_the_link_looks_like():
    ids = ["https://youtu.be/XXKXpf7xFC4?si=abc", "https://www.youtube.com/watch?v=XXKXpf7xFC4&list=RD1", "https://music.youtube.com/watch?v=XXKXpf7xFC4",
           "youtu.be/XXKXpf7xFC4", "https://www.youtube.com/shorts/XXKXpf7xFC4"]
    assert len({R.link_key(i) for i in ids}) == 1
    assert R.link_key("https://open.spotify.com/track/abc?si=zzz") == "https://open.spotify.com/track/abc"


def test_plan_says_done_pending_failed_and_removed():
    links = ["https://youtu.be/AAAAAAAAAAA", "https://youtu.be/BBBBBBBBBBB", "https://youtu.be/CCCCCCCCCCC"]
    tracks = [T(links[0], "one"), T("https://youtu.be/DDDDDDDDDDD", "gone"), T(links[2], "three", ok=False)]
    p = R.plan(links, tracks)
    assert [r["status"] for r in p["rows"]] == ["done", "pending", "failed"]
    assert (p["done"], p["pending"], p["failed"]) == (1, 1, 1) and p["removed"][0]["title"] == "gone"
    assert R.todo(links, tracks) == [links[1], links[2]]                    # new ones and failed ones are (re)extracted, done ones are not


def test_reconcile_drops_removed_songs_follows_the_new_order_and_keeps_files_untouched():
    a, b, c = (f"https://youtu.be/{x * 11}" for x in "ABC")
    tracks = [T(a, "A"), T(b, "B"), T(c, "C")]
    kept, removed = R.reconcile([c, a], tracks)                              # B removed, C moved before A
    assert [t["title"] for t in kept] == ["C", "A"] and [t["title"] for t in removed] == ["B"]
    kept, _ = R.reconcile([a, b, c, "https://youtu.be/" + "D" * 11], tracks)  # a new link: nothing lost, nothing invented
    assert [t["title"] for t in kept] == ["A", "B", "C"]


def test_a_link_listed_twice_gets_two_tracks_one_each_and_a_playlist_link_keeps_all_its_songs():
    a = "https://youtu.be/" + "A" * 11
    two = [T(a, "first"), T(a, "second")]
    assert [t["title"] for t in R.reconcile([a, a], two)[0]] == ["first", "second"]
    folder = "/music/album"
    songs = [T(folder, "s1"), T(folder, "s2"), T(folder, "s3")]
    assert len(R.reconcile([folder], songs)[0]) == 3


def test_older_projects_without_link_notes_keep_their_songs_when_counts_match():
    old = [{"title": "o1", "audio": "a.mp3"}, {"title": "o2", "audio": "b.mp3"}]
    kept, removed = R.reconcile(["https://youtu.be/" + "A" * 11, "https://youtu.be/" + "B" * 11], old)
    assert [t["title"] for t in kept] == ["o1", "o2"] and removed == []
