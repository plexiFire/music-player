from engine.video import timestamps


def test_timestamp_format_and_starts():
    tr = [{"title": "A", "artist": "x"}, {"title": "B", "artist": "y"}]
    starts, text = timestamps.build(tr, [185.4, 60])
    assert starts == [0.0, 185.4]
    assert text.splitlines() == ["0:00 A - x", "3:05 B - y"]
    assert timestamps.fmt(3725) == "1:02:05"


def test_timestamps_omit_empty_artist():
    _, text = timestamps.build([{"title": "Only Title", "artist": ""}], [10])
    assert text == "0:00 Only Title"
