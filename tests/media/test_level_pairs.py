import subprocess

from engine.media import level


def ff(*a):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True)


def tone(path, secs, volume):
    ff("-f", "lavfi", "-i", f"sine=frequency=330:duration={secs}", "-af", f"volume={volume}", str(path))
    return str(path)


def test_boundary_jump_is_end_of_one_minus_start_of_the_next():
    a = [-10.0] * 60                       # 30 s at -10 dB
    b = [-20.0] * 60                       # 30 s at -20 dB
    j = level.boundary_jumps([a, b])
    assert j == [{"i": 1, "end_db": -10.0, "start_db": -20.0, "fade": False, "jump": 10.0}]
    assert level.boundary_jumps([[-90.0] * 20, b])[0]["jump"] is None            # silence: nothing to compare


def test_pairs_mode_splits_the_correction_between_the_two_sides_and_touches_only_the_chosen_boundaries():
    a, b, c = [-10.0] * 60, [-20.0] * 60, [-10.0] * 60            # 1->2 jumps 10 dB, 2->3 jumps -10 dB
    plan = level.plan_gains([-10, -20, -10], [a, b, c], "pairs", pairs=[1])
    assert plan[0] == {"whole": 0.0, "start": 0.0, "end": -5.0}   # end of song 1 goes down 5
    assert plan[1] == {"whole": 0.0, "start": 5.0, "end": 0.0}    # start of song 2 goes up 5, its END is untouched (boundary 2->3 not chosen)
    assert plan[2] == {"whole": 0.0, "start": 0.0, "end": 0.0}
    after = [level.predict(x, p, 30.0) for x, p in zip((a, b, c), plan)]
    assert abs(level.boundary_jumps(after)[0]["jump"]) < 0.3      # the chosen jump is gone
    assert level.boundary_jumps(after)[1]["jump"] == -10.0        # the other one is exactly as before
    assert level.plan_gains([-10, -20, -10], [a, b, c], "off") == [{"whole": 0.0, "start": 0.0, "end": 0.0}] * 3
    both = level.plan_gains([-10, -20, -10], [a, b, c], "pairs", pairs=[1, 2])
    assert both[1] == {"whole": 0.0, "start": 5.0, "end": 5.0}    # a song can be adjusted at both ends, each for its own boundary (here song 3 is louder, so song 2's end goes up)


def test_whole_mode_is_one_gain_per_song():
    plan = level.plan_gains([-10.0, -20.0], [[-10.0] * 20, [-20.0] * 20], "whole")
    assert plan[0]["whole"] == -4.0 and plan[1]["whole"] == 6.0 and plan[0]["start"] == plan[0]["end"] == 0.0


def test_the_ffmpeg_gain_matches_the_predicted_graph_and_the_middle_of_a_song_is_left_alone(tmp_path):
    loud = tone(tmp_path / "loud.wav", 30, 3)
    quiet = tone(tmp_path / "quiet.wav", 30, 0.6)                 # ~14 dB quieter
    ca, cb = level.curve(loud), level.curve(quiet)
    plan = level.plan_gains([-10, -24], [ca, cb], "pairs", pairs=[1])
    out_b = level.apply_plan(quiet, str(tmp_path / "qb.mp3"), plan[1], 30.0)
    out_a = level.apply_plan(loud, str(tmp_path / "la.mp3"), plan[0], 30.0)
    real_b, real_a = level.curve(out_b), level.curve(out_a)
    pred_b = level.predict(cb, plan[1], 30.0)
    assert abs(real_b[1] - pred_b[1]) < 1.0 and abs(real_b[6] - pred_b[6]) < 1.0           # the start of song 2 really went up as predicted
    assert abs(real_b[40] - cb[40]) < 0.6                                                  # 20 s in, nothing changed
    assert abs(real_a[-2] - (ca[-2] + plan[0]["end"])) < 1.0 and abs(real_a[10] - ca[10]) < 0.6
    after_jump = level.edge_level(real_a, "end") - level.edge_level(real_b, "start")
    assert abs(after_jump) < 1.0 < abs(level.boundary_jumps([ca, cb])[0]["jump"])           # was ~14 dB, is now about 0 (measured on the real audio)


def test_the_listening_clip_for_a_boundary_can_be_built_before_and_after(tmp_path):
    a, b = tone(tmp_path / "a.wav", 20, 3), tone(tmp_path / "b.wav", 20, 0.6)
    plan = level.plan_gains([-10, -24], [level.curve(a), level.curve(b)], "pairs", pairs=[1])
    neutral = {"whole": 0.0, "start": 0.0, "end": 0.0}
    before = level.demo_clip_plan(a, b, neutral, neutral, 20.0, 20.0, str(tmp_path / "before.mp3"), secs=8)
    after = level.demo_clip_plan(a, b, plan[0], plan[1], 20.0, 20.0, str(tmp_path / "after.mp3"), secs=8)
    cb4, ca4 = level.curve(before), level.curve(after)
    jump = lambda c: (sum(c[:16]) / 16) - (sum(c[16:]) / 16)                                # first half (end of a) minus second half (start of b)
    assert jump(ca4) < jump(cb4) - 3                                                          # the jump between the two songs got smaller


def test_a_normal_fade_out_is_not_mistaken_for_a_volume_jump():
    fade = [-10.0] * 80 + [-10.0 - 4 * k for k in range(1, 13)]          # the music at -10 dB, then a 6 s fade down to -58
    flat = [-10.0] * 60
    assert abs(level.boundary_jumps([fade, flat])[0]["jump"]) < 3.0       # a 6 s fade is not "a noticeable jump" (before: about -45 dB)
    longer = [-10.0] * 80 + [-10.0 - 3 * k for k in range(1, 16)]          # an even longer fade is still far from the old "big jump"
    assert abs(level.boundary_jumps([longer, [-10.0] * 60])[0]["jump"]) < 15


def test_a_slow_start_after_a_loud_ending_is_flagged():
    a = [-8.0] * 60
    b = [-22.0] * 10 + [-8.0] * 50                                        # song 2 starts soft for 5 s
    assert level.boundary_jumps([a, b])[0]["jump"] == 14.0


def test_values_set_by_hand_replace_the_automatic_ones_and_stay_in_range():
    a, b = [-8.0] * 60, [-22.0] * 60
    auto = level.plan_gains([-8, -22], [a, b], "pairs", [1])
    assert auto[0]["end"] == -7.0 and auto[1]["start"] == 7.0              # half and half
    hand = level.plan_gains([-8, -22], [a, b], "pairs", [1], adjust={1: {"end": -1.0, "start": 3.3}})
    assert hand[0]["end"] == -1.0 and hand[1]["start"] == 3.5              # your numbers, in half-dB steps
    wild = level.plan_gains([-8, -22], [a, b], "pairs", [1], adjust={1: {"end": 99, "start": -99}})
    assert wild[0]["end"] == level.MAX_GAIN and wild[1]["start"] == -level.MAX_GAIN
    off = level.plan_gains([-8, -22], [a, b], "pairs", [], adjust={1: {"end": 5, "start": 5}})
    assert off[0]["end"] == 0.0 and off[1]["start"] == 0.0                 # not ticked: hand values are ignored
    assert level.adjust_of({"level_adjust": {"1": {"end": "-2", "start": 3}, "x": 5}}) == {1: {"end": -2.0, "start": 3.0}}


def test_a_song_that_fades_out_keeps_its_ending_and_only_the_next_start_follows_the_music():
    a = [-8.0] * 80 + [-8.0 - 3 * k for k in range(1, 21)]                # music at -8 dB, then a 10 s fade
    b = [-18.0] * 60                                                      # the next song starts 10 dB quieter than that music
    j = level.boundary_jumps([a, b])[0]
    assert j["fade"] is True and j["end_db"] == -8.0 and j["jump"] == 10.0
    plan = level.plan_gains([-8, -18], [a, b], "pairs", [1])
    assert plan[0]["end"] == 0.0 and plan[1]["start"] == 10.0              # the fade is not lifted; the next start rises by the full 10
    after = [level.predict(c, p, 60.0) for c, p in zip((a, b), plan)]
    assert abs(level.boundary_jumps(after)[0]["jump"]) < 0.5
    hard = level.boundary_jumps([[-8.0] * 100, b])[0]
    assert hard["fade"] is False                                          # a song with a hard ending is split half and half as before
