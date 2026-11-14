"""Finds out WHY YouTube refuses a machine ('Sign in to confirm you're not a bot'), by changing one thing at a time.

  python scripts/yt_diagnose.py [--url URL] [--cookies cookies.txt] [--pot-url http://127.0.0.1:4416]

Each row runs `yt-dlp -J` (details only, no download) with ONE change: a different YouTube client, a logged-in cookie file, or a
PO-Token provider (bgutil). Compare the same table from two machines (e.g. your Mac vs a GitHub runner):
  Mac OK, runner BLOCKED            -> the network/environment differs (IP reputation is the main suspect)
  everything BLOCKED on both        -> a broader extraction/authentication problem
  cookies row OK, default BLOCKED   -> a session matters
  provider row OK, default BLOCKED  -> a PO token matters
No cookies, tokens or IP addresses are printed. Exit code is always 0: a BLOCKED row is a finding."""
import argparse
import json
import os
import platform
import shutil
import ssl
import subprocess
import sys
import time

CLIENTS = ["web", "mweb", "tv", "web_embedded", "ios", "android"]


def classify(returncode, stderr):
    """('OK' | 'BLOCKED' | 'UNAVAILABLE' | 'ERROR', short reason)."""
    if returncode == 0:
        return "OK", ""
    last = (stderr.strip().splitlines() or ["?"])[-1]
    low = stderr.lower()
    if "not a bot" in low or "sign in to confirm" in low:
        return "BLOCKED", "sign in to confirm you're not a bot"
    if "unavailable" in low or "private video" in low:
        return "UNAVAILABLE", last[:100]
    return "ERROR", last[:100]


def ytdlp_cmd():
    exe = shutil.which("yt-dlp")
    return [exe] if exe else [sys.executable, "-m", "yt_dlp"]


def supports(flag):
    try:
        return flag in subprocess.run(ytdlp_cmd() + ["--help"], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return False


def run_case(name, extra, url, notes=False):
    cmd = ytdlp_cmd() + ["--ignore-config", "-J", "--no-playlist", "--no-warnings"] + (["-v"] if notes else []) + extra + [url]
    if supports("--js-runtimes") and shutil.which("node"):
        cmd[len(ytdlp_cmd()) + 1:len(ytdlp_cmd()) + 1] = ["--js-runtimes", "node"]
    t = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
        status, why = classify(r.returncode, r.stderr)
        seen = [l.strip()[:110] for l in r.stderr.splitlines() if notes and ("PO Token" in l or "bgutil" in l.lower()) and "Cookie" not in l][:2]
    except subprocess.TimeoutExpired:
        status, why, seen = "ERROR", "timed out after 120 s", []
    return {"case": name, "result": status, "detail": why, "seconds": round(time.time() - t, 1), "notes": " | ".join(seen)}


def where_am_i():
    """What kind of network this is, without printing the address: just the provider name."""
    try:
        import requests
        j = requests.get("https://ipinfo.io/json", timeout=10).json()
        return j.get("org", "unknown network"), j.get("country", "")
    except Exception:
        return "unknown network", ""


def pot_alive(url):
    try:
        import requests
        return requests.get(url.rstrip("/") + "/ping", timeout=5).status_code == 200
    except Exception:
        return False


def build_cases(cookies, pot_url):
    cases = [("default", [], False)]
    cases += [(f"client={c}", ["--extractor-args", f"youtube:player_client={c}"], False) for c in CLIENTS]
    if cookies:
        cases.append(("cookies", ["--cookies", cookies], False))
    if pot_url and pot_alive(pot_url):
        cases.append(("PO-token provider", ["--extractor-args", f"youtubepot-bgutilhttp:base_url={pot_url}"], True))
        if cookies:
            cases.append(("cookies + PO-token provider", ["--cookies", cookies, "--extractor-args", f"youtubepot-bgutilhttp:base_url={pot_url}"], True))
    elif pot_url:
        cases.append(("PO-token provider", None, False))               # asked for, but the provider is not running
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://www.youtube.com/watch?v=jNQXAC9IVRw")
    ap.add_argument("--cookies", default=os.environ.get("SENORA_YT_COOKIES_FILE"))
    ap.add_argument("--pot-url", help="base URL of a running bgutil provider, e.g. http://127.0.0.1:4416")
    a = ap.parse_args()
    cookies = a.cookies if a.cookies and os.path.exists(a.cookies) else None
    ver = subprocess.run(ytdlp_cmd() + ["--version"], capture_output=True, text=True).stdout.strip()
    org, country = where_am_i()
    lines = ["## YouTube diagnosis", "",
             f"- network: **{org}** {country} | yt-dlp **{ver}** | Python {platform.python_version()} | {ssl.OPENSSL_VERSION}",
             f"- cookies: **{'yes' if cookies else 'no'}** | PO-token provider asked for: **{'yes' if a.pot_url else 'no'}**", "",
             "| change | result | detail | s | PO-token log lines |", "|---|---|---|---|---|"]
    for name, extra, notes in build_cases(cookies, a.pot_url):
        row = run_case(name, extra, a.url, notes) if extra is not None else \
            {"case": name, "result": "NOT RUN", "detail": "provider not reachable", "seconds": 0, "notes": ""}
        lines.append(f"| {row['case']} | **{row['result']}** | {row['detail']} | {row['seconds']} | {row['notes']} |")
    report = "\n".join(lines)
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write(report + "\n")


if __name__ == "__main__":
    main()
