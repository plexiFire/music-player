"""UI smoke test: starts the real server and drives the page in a headless browser. Offline: no YouTube, no Groq.
Needs `pip install playwright` and a browser (`playwright install chromium`); without Playwright these tests are skipped,
so the normal `pytest` run stays light. CI runs them in their own job (see .github/workflows/tests.yml)."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
SAMPLES = os.path.abspath(os.path.join(ROOT, "samples"))
PID = "a1b2c3d4"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url):
    return json.load(urllib.request.urlopen(url, timeout=20))


def call(url, method, body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data = tmp_path_factory.mktemp("senora_data")
    d = data / PID
    for sub in ("audio", "work", "out"):
        (d / sub).mkdir(parents=True)
    tracks = [{"title": f"Song {i}", "artist": "Band", "audio": f"{SAMPLES}/tone{i}.wav", "cover": f"{SAMPLES}/cover{i}.png",
               "duration": 3.0, "source_link": f"https://youtu.be/aaaaaaaaaa{i}"} for i in (1, 2, 3)]
    json.dump({"id": PID, "name": "Smoke playlist", "title": "Smoke playlist", "theme": "Smoke playlist", "created": time.time(),
               "links": [t["source_link"] for t in tracks], "tracks": tracks, "rights_confirmed": True, "mood": "slow, calm",
               "channel": "Senora", "contact_email": "", "hashtags": [], "disc": "vinyl", "youtube_title": "",
               "background": {"mode": "cover"}, "watermark": True}, open(d / "project.json", "w"))
    port = free_port()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "server.app:app", "--port", str(port)], cwd=ROOT,
                            env={**os.environ, "SENORA_DATA": str(data)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            get(base + "/api/library")
            break
        except Exception:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("the server did not start")
    yield base
    proc.terminate()


@pytest.fixture()
def page(server):
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            browser = p.chromium.launch(channel="chrome")       # a machine that has Chrome but no downloaded Chromium
        pg = browser.new_page(viewport={"width": 1300, "height": 1000})
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.on("dialog", lambda d: d.accept())
        yield pg
        browser.close()


def wait_until(check, seconds=15):
    """Poll until check() is truthy (the page saves in the background, so fixed sleeps are flaky)."""
    end = time.time() + seconds
    while time.time() < end:
        try:
            r = check()
            if r:
                return r
        except Exception:
            pass
        time.sleep(0.3)
    raise AssertionError("condition not met in time")


def open_step(pg, base, step):
    pg.goto(base)
    pg.wait_for_timeout(800)
    pg.evaluate("async ([id, stepNo]) => { mode = 'pl'; await loadProjects(id); step = stepNo; render(); }", [PID, step])


def test_home_shows_the_library_and_the_playlist_cards_without_script_errors(page, server):
    page.goto(server)
    page.wait_for_selector(".cat", timeout=15000)
    assert page.locator(".cat").count() >= 50 and page.locator("#libBtn").count() == 1
    assert page.locator(".pcard").count() == 1 and "Smoke playlist" in page.inner_text(".pcard")
    assert page.locator(".bin").count() == 1                               # every playlist card has its bin
    assert page.errors == []


def test_library_category_can_be_made_opened_and_deleted(page, server):
    page.goto(server)
    page.wait_for_selector("#newCat")
    page.fill("#newCat", "Smoke walks")
    page.click("#addCat")
    page.wait_for_selector("#libAdd")                                      # the new category's sheet opened
    assert "Smoke walks" in page.inner_text("h2")
    page.click("#delCat")
    page.wait_for_selector("#newCat")
    assert "Smoke walks" not in page.inner_text("body")
    assert page.errors == []


def test_build_page_has_thumbnail_gallery_editable_description_and_cloud_job(page, server):
    open_step(page, server, 3)
    page.wait_for_selector(".fam", timeout=20000)
    assert page.locator(".fam").count() == 7
    page.locator(".fam[data-f='night'] > .hd").click()
    page.locator(".fam[data-f='swirl'] > .hd").click()
    assert page.locator(".fam.open").count() == 2                          # opening one does not close the other
    page.locator(".fam[data-f='night'] .tile").first.click()
    assert wait_until(lambda: get(f"{server}/api/projects/{PID}")["thumbs_selected"][0]["family"] == "night")
    page.wait_for_selector("#pv_desc")
    page.wait_for_timeout(2500)
    assert page.locator("#pv_desc").is_editable()
    page.evaluate("() => { const t = document.querySelector('#pv_desc'); t.value += '\\nMY OWN LINE'; t.dispatchEvent(new Event('input')); }")
    assert wait_until(lambda: "MY OWN LINE" in get(f"{server}/api/projects/{PID}")["description_override"])
    job = get(f"{server}/api/projects/{PID}/cloud-job")
    assert job["authorized"] is True and len(job["links"]) == 3 and "contact_email" not in json.dumps(job)
    assert page.errors == []


def test_tracks_page_shows_volume_card_with_the_simple_controls(page, server):
    open_step(page, server, 2)
    page.wait_for_selector("#lvOn", timeout=20000)
    assert page.locator("#lvOrig").count() == 1 and page.locator("#lvEven").count() == 1 and not page.is_checked("#lvOn")
    assert page.locator("[data-spd='1'] option").count() == 8              # speeds up to 3x
    assert page.errors == []
