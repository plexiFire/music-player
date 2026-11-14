import importlib.util
import os

spec = importlib.util.spec_from_file_location("yt_diagnose", os.path.join(os.path.dirname(__file__), "..", "scripts", "yt_diagnose.py"))
yd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(yd)


def test_results_are_classified_in_plain_words():
    assert yd.classify(0, "")[0] == "OK"
    assert yd.classify(1, "ERROR: [youtube] x: Sign in to confirm you’re not a bot. Use --cookies")[0] == "BLOCKED"
    assert yd.classify(1, "ERROR: [youtube] x: Video unavailable")[0] == "UNAVAILABLE"
    assert yd.classify(1, "ERROR: something else")[0] == "ERROR"


def test_each_case_changes_exactly_one_thing_and_secrets_stay_out():
    cases = dict((n, e) for n, e, _ in yd.build_cases("/tmp/c.txt", None))
    assert cases["default"] == [] and "--cookies" in cases["cookies"]
    assert [n for n in cases if n.startswith("client=")] == [f"client={c}" for c in yd.CLIENTS]
    assert "PO-token provider" not in cases                      # not asked for -> not in the table
    assert "cookies" not in dict((n, e) for n, e, _ in yd.build_cases(None, None))
