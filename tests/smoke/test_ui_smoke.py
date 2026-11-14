"""UI smoke test: starts the real server and drives the page in a headless browser. Offline: no YouTube, no Groq.
Needs `pip install playwright` and a browser (`playwright install chromium`); without Playwright these tests are skipped,
so the normal `pytest` run stays light. CI runs them in their own job (see .github/workflows/tests.yml)."""
import json
import os
import socket
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
SAMPLES = os.path.abspath(os.path.join(ROOT, "samples"))
PID = "a1b2c3d4"
STATE = {}                            # the server fixture puts its data folder here
L = lambda c: f"https://youtu.be/{c * 11}"


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


def make_editing_project():
    """A fresh playlist for ONE test: two 40-second songs and a third link that is not extracted yet."""
    import uuid
    pid = uuid.uuid4().hex[:8]
    d = STATE["data"] / pid
    for sub in ("audio", "work", "out"):
        (d / sub).mkdir(parents=True)
    tracks = []
    for i, c in enumerate("AB", 1):
        f = d / "audio" / f"long{i}.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={300 + 90 * i}:duration=40", str(f)], check=True)
        tracks.append({"title": f"Long {i}", "artist": "Band", "audio": str(f), "cover": f"{SAMPLES}/cover{i}.png", "duration": 40.0,
                       "from_link": L(c), "source_link": L(c)})
    json.dump({"id": pid, "name": "Editing playlist", "title": "Editing playlist", "theme": "Editing playlist", "created": time.time(),
               "links": [L("A"), L("B"), L("C")], "tracks": tracks, "rights_confirmed": True, "mood": "calm", "channel": "Senora",
               "contact_email": "me@example.com", "hashtags": [], "disc": "vinyl", "youtube_title": "", "background": {"mode": "cover"}},
              open(d / "project.json", "w"))
    return pid


@pytest.fixture()
def editing(server):
    return make_editing_project()


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
    STATE["data"] = data
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
        pg.on("pageerror", lambda e: pg.errors.append(str(e) + " | " + str(getattr(e, "stack", ""))[:400]))
        pg.prompt_answer = ""                                    # what a prompt() dialog should be answered with
        pg.on("dialog", lambda d: d.accept(pg.prompt_answer) if d.type == "prompt" else d.accept())
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


def open_step(pg, base, step, pid=PID):
    pg.goto(base)
    pg.wait_for_timeout(800)
    pg.evaluate("async ([id, stepNo]) => { mode = 'pl'; await loadProjects(id); step = stepNo; render(); }", [pid, step])


def test_home_shows_the_library_and_the_playlist_cards_without_script_errors(page, server):
    page.goto(server)
    page.wait_for_selector(".cat", timeout=15000)
    assert page.locator(".cat").count() >= 50 and page.locator("#libBtn").count() == 1
    assert page.locator(".pcard").count() >= 1 and "Smoke playlist" in page.inner_text("body")
    assert page.locator(".bin").count() == page.locator(".pcard").count()  # every playlist card has its bin
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
    assert page.locator(".fam").count() == 11
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


def test_volume_card_is_simple_three_choices_a_graph_and_boundary_ticks_that_are_saved(page, server, editing):
    open_step(page, server, 2, editing)
    page.wait_for_selector("#lvGraph", timeout=40000)
    assert page.locator("[data-lvmode]").count() == 3 and page.get_attribute('[data-lvmode="off"]', "aria-pressed") == "true"
    assert "dB" not in page.inner_text("#levelCard")                       # words and colours, no technical numbers
    assert page.locator("[data-hear]").count() == 1                        # off: one boundary, one "Listen"
    ink = page.evaluate("() => { const c = document.querySelector('#lvGraph'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i]) n++; return n; }")
    assert ink > 500                                                       # the graph is really drawn
    page.click('[data-lvmode="whole"]')
    wait_until(lambda: get(f"{server}/api/projects/{editing}").get("level_mode") == "whole")
    page.click('[data-lvmode="pairs"]')
    page.wait_for_selector('[data-pair="1"]')
    page.check('[data-pair="1"]')
    state = wait_until(lambda: (lambda p: p if p.get("level_pairs") == [1] else None)(get(f"{server}/api/projects/{editing}")))
    assert state["level_mode"] == "pairs" and state["level_audio"] is True
    assert page.locator("[data-hear]").count() == 2                        # now Before and After
    page.wait_for_selector('[data-sl="1:end"]')                            # two sliders per ticked boundary
    assert "Changes only the last 12 seconds" in page.inner_text("#lvPairs") and "only a little of each song" in page.inner_text("#lvScope").lower()
    page.evaluate("""() => { for (const [k, v] of [['end', -2], ['start', 3]]) { const s = document.querySelector(`[data-sl="1:${k}"]`);
        s.value = v; s.dispatchEvent(new Event('input', {bubbles: true})); s.dispatchEvent(new Event('change', {bubbles: true})); } }""")
    state = wait_until(lambda: (lambda p: p if p.get("level_adjust", {}).get("1") == {"end": -2.0, "start": 3.0} else None)(get(f"{server}/api/projects/{editing}")))
    assert state["level_pairs"] == [1]                                     # your own values are saved
    page.click('[data-lvmode="whole"]')
    page.wait_for_function("document.querySelector('#lvScope').innerText.includes('whole of every song')")
    page.click('[data-lvmode="pairs"]')
    page.wait_for_selector('[data-sl="1:end"]')
    page.click('[data-hear="1:after"]')
    page.wait_for_function("document.querySelector('#lvAudio').src.includes('version=after')")
    assert page.locator("[data-spd='1'] option").count() == 8              # speeds up to 3x
    assert page.errors == []


def test_after_a_cut_the_picture_the_player_and_the_fields_all_use_the_same_timeline(page, server, editing):
    open_step(page, server, 2, editing)
    page.wait_for_selector('[data-cutd="1"]')
    page.locator('[data-cutd="1"] summary').click()
    page.fill('[data-s="1"]', "0:05")
    page.fill('[data-e="1"]', "0:35")
    assert "Keeps 0:05 to 0:35" in page.inner_text('[data-keeps="1"]')
    page.click('[data-trim="1"]')
    t = wait_until(lambda: (lambda x: x if x["tracks"][0].get("trim") else None)(get(f"{server}/api/projects/{editing}")))
    assert t["tracks"][0]["trim"]["start"] == 5.0 and abs(t["tracks"][0]["duration"] - 30.0) < 0.5
    page.wait_for_selector('[data-cutd="1"] summary')
    page.wait_for_timeout(1800)                                            # the waveform of the cut audio loads
    assert "now" in page.inner_text(".okbox") and "0:30" in page.inner_text(".okbox")
    assert page.input_value('[data-s="1"]') == "0:00" and page.input_value('[data-e="1"]') == "0:30"      # fields = the audio you hear now
    alpha = page.evaluate("""() => { const cv = document.querySelector('canvas[data-wave="1"]'), c = cv.getContext('2d');
        const a = x => Math.max(...Array.from(c.getImageData(x, cv.height / 2 - 6, 8, 12).data).filter((_, i) => i % 4 === 3));
        return [a(4), a(Math.floor(cv.width / 2)), a(cv.width - 14)]; }""")
    assert min(alpha) > 200                                                # a dimmed 'removed' part would be about 140: none in a song that was already cut
    # a second cut is typed against the 30 s you hear: 0:02-0:12 means 0:07-0:17 of the original
    page.locator('[data-cutd="1"] summary').click()
    page.fill('[data-s="1"]', "0:02")
    page.fill('[data-e="1"]', "0:12")
    page.click('[data-trim="1"]')
    t = wait_until(lambda: (lambda x: x if abs(x["tracks"][0]["duration"] - 10.0) < 0.5 else None)(get(f"{server}/api/projects/{editing}")))
    assert t["tracks"][0]["trim"]["start"] == 7.0 and t["tracks"][0]["trim"]["end"] == 17.0
    assert page.errors == []


def test_markers_on_the_waveform_can_be_dragged_and_nudged_and_wrong_times_are_refused(page, server, editing):
    open_step(page, server, 2, editing)
    page.wait_for_selector('[data-cutd="2"]')
    page.wait_for_timeout(1500)
    page.locator('[data-cutd="2"] summary').click()
    box = page.locator('canvas[data-wave="2"]').bounding_box()
    page.mouse.move(box["x"] + 2, box["y"] + 30)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + 30, steps=6)
    page.mouse.up()
    start = page.input_value('[data-s="2"]')
    assert start.startswith("0:19") or start.startswith("0:20") or start.startswith("0:21"), start      # half of 40 s
    page.click('[data-nudge="2:s:1"]')
    assert page.input_value('[data-s="2"]') != start
    page.fill('[data-s="2"]', "abc")
    page.click('[data-trim="2"]')
    assert "Type the times like 1:05" in page.inner_text('[data-msg="2"]') or "minutes:seconds" in page.inner_text('[data-msg="2"]')
    page.fill('[data-s="2"]', "0:30")
    page.fill('[data-e="2"]', "0:20")
    page.click('[data-trim="2"]')
    assert "later than" in page.inner_text('[data-msg="2"]')
    page.fill('[data-s="2"]', "0:10")
    page.fill('[data-e="2"]', "1:30")
    page.click('[data-trim="2"]')
    assert "only 0:40 long" in page.inner_text('[data-msg="2"]')
    assert page.errors == []


def test_totals_links_status_extract_plan_and_removing_a_song_with_undo(page, server, editing):
    open_step(page, server, 0, editing)
    page.wait_for_selector("[data-st]")
    assert "Total length 1:20" in page.inner_text("#sumbar") and "1 not extracted yet" in page.inner_text("#sumbar")
    st = page.locator("[data-st]").all_inner_texts()
    assert st[0].startswith("✓ 0:40") and st[1].startswith("✓ 0:40") and st[2] == "not extracted"
    open_step(page, server, 1, editing)
    page.wait_for_selector("#plan")
    assert page.inner_text("#go") == "Extract 1 song" and "2 of 3 links done" in page.inner_text(".card")
    open_step(page, server, 2, editing)
    page.wait_for_selector("[data-rmtrack]")
    assert "1 song(s) of your links are not extracted yet" in page.inner_text(".card")
    assert "starts at 0:40" in page.inner_text('.track[data-n="2"]')
    page.locator('[data-rmtrack="1"]').click()
    page.wait_for_function("document.querySelectorAll('[data-rmtrack]').length === 1")
    api = get(f"{server}/api/projects/{editing}")
    assert [t["title"] for t in api["tracks"]] == ["Long 2"] and L("A") not in api["links"]
    assert "Total length 0:40" in page.inner_text("#sumbar")
    page.click("#toast button")                                            # Undo in the toast
    page.wait_for_function("document.querySelectorAll('[data-rmtrack]').length === 2")
    api = get(f"{server}/api/projects/{editing}")
    assert [t["title"] for t in api["tracks"]] == ["Long 1", "Long 2"] and api["links"][0] == L("A")
    assert page.errors == []


def test_your_own_titles_can_be_added_edited_and_crossed_out_and_the_gpt_brief_is_ready(page, server, editing):
    open_step(page, server, 3, editing)
    page.wait_for_selector("#addTitle", timeout=20000)
    page.wait_for_selector("#titleOpts .chip")
    n0 = page.locator("#titleOpts .tw").count()
    page.fill("#newTitle", "[Playlist] Songs for my own people")
    page.click("#addTitle")
    page.wait_for_function("document.querySelector('#titleOpts .chip').dataset.title === '[Playlist] Songs for my own people'")
    assert page.locator("#titleOpts .tw").count() == n0 + 1 and "yours" in page.locator("#titleOpts .chip").first.inner_text()
    page.prompt_answer = "[Playlist] Songs for my crew"
    page.locator("#titleOpts [data-edit]").first.click()
    page.wait_for_function("document.querySelector('#titleOpts .chip').dataset.title === '[Playlist] Songs for my crew'")
    second = page.locator("#titleOpts .chip").nth(1).get_attribute("data-title")
    page.locator("#titleOpts [data-del]").nth(1).click()                   # cross out a suggested title
    page.wait_for_function("t => ![...document.querySelectorAll('#titleOpts .chip')].some(c => c.dataset.title === t)", arg=second)
    assert "removed are hidden" in page.inner_text("#titleAdd")
    page.click("#restoreTitles")
    page.wait_for_function("t => [...document.querySelectorAll('#titleOpts .chip')].some(c => c.dataset.title === t)", arg=second)
    page.locator("#titleOpts [data-del]").first.click()                    # cross out your own: it is deleted
    page.wait_for_function("document.querySelector('#titleOpts .chip').dataset.title !== '[Playlist] Songs for my crew'")
    page.fill("#gptQ", "Is the title too generic?")
    page.click("#gptCopy")
    page.wait_for_function("document.querySelector('#gptText').value.includes('MY QUESTION: Is the title too generic?')", timeout=20000)
    text = page.input_value("#gptText")
    assert "## Songs in order" in text and "Long 1" in text and "total length 1:20" in text and "me@example.com" not in text
    zipped = urllib.request.urlopen(f"{server}/api/projects/{editing}/gpt-pack.zip", timeout=30).read()
    assert zipped[:2] == b"PK" and page.errors == []


def test_a_closed_page_comes_back_where_it_was_and_what_you_type_is_saved_without_pressing_save(page, server, editing):
    open_step(page, server, 3, editing)
    page.wait_for_selector("#s_mood", timeout=20000)
    page.fill("#s_mood", "rainy and slow")                                  # no Save button pressed
    page.fill("#s_title", "[Playlist] Typed and not saved by hand")
    wait_until(lambda: (lambda p: p.get("mood") == "rainy and slow" and p.get("youtube_title") == "[Playlist] Typed and not saved by hand")(
        get(f"{server}/api/projects/{editing}")))
    wait_until(lambda: get(f"{server}/api/ui-state").get("pid") == editing and get(f"{server}/api/ui-state").get("step") == 3)
    page.goto(server)                                                       # a fresh page, as after the server or the browser was closed
    page.wait_for_selector("#s_mood", timeout=20000)                        # straight back to the Build step of that playlist
    assert page.input_value("#s_mood") == "rainy and slow"
    open_step(page, server, 0, editing)
    page.wait_for_selector("#rows input")
    page.locator("#rows input").last.fill(L("D"))                           # a new link typed in the empty row, not left yet
    wait_until(lambda: L("D") in get(f"{server}/api/projects/{editing}")["links"])
    assert page.errors == []


def test_a_job_the_server_lost_is_explained_in_plain_words(page, server, editing):
    jobs = STATE["data"] / "_jobs"
    jobs.mkdir(exist_ok=True)
    json.dump({"id": "deadbeef", "kind": "build", "project": editing, "state": "running", "message": "stage 1/4: video", "started": time.time() - 90, "log": ""},
              open(jobs / "deadbeef.json", "w"))                           # a record left by a server that stopped in the middle of a build
    page.goto(server)
    page.wait_for_selector("#libBtn", timeout=15000)      # the page may reopen where an earlier test left it, so do not wait for the home categories
    text = page.evaluate("""async (id) => { mode = 'pl'; await loadProjects(id); step = 3; render();
        const box = document.createElement('div'); document.body.appendChild(box);
        watch('deadbeef', box, () => {}, 'build', 60); await new Promise(r => setTimeout(r, 2200)); return box.innerText; }""", editing)
    assert "Stopped" in text and "press the button again" in text and "Something went wrong" not in text
    assert page.errors == []


def test_library_cards_can_be_renamed_and_removed_and_removed_ones_brought_back(page, server):
    page.goto(server)
    page.wait_for_selector("#libBtn", timeout=15000)                       # the page may reopen where an earlier test left it
    page.evaluate("() => { mode = 'lib'; catId = null; render(); }")
    page.wait_for_selector('[data-ren="sad-songs"]')
    page.prompt_answer = "Rainy day songs"
    page.click('[data-ren="sad-songs"]')
    page.wait_for_function("() => document.body.innerText.includes('Rainy day songs')")
    assert "Sad songs" not in page.inner_text(".cats")
    page.click('[data-delcat="heartbreak"]')
    page.wait_for_function("() => !document.querySelector('[data-delcat=\"heartbreak\"]')")
    assert "Heartbreak" not in page.inner_text("body").split("Bring the removed ones back")[0]
    page.click("#restoreCats")
    page.wait_for_selector('[data-delcat="heartbreak"]')
    page.click('.cat[data-cat="sad-songs"]')                               # the open category also has Rename and Delete
    page.wait_for_selector("#renCat")
    assert page.locator("#delCat").count() == 1
    assert page.errors == []


def test_on_github_pages_pictures_and_downloads_point_at_the_mac(page, server):
    """The page copy on github.io reaches the Senora on the Mac by an absolute address, including for images and download links."""
    html = (Path(__file__).resolve().parents[2] / "server" / "static" / "index.html").read_text()
    page.route("https://plexifire.github.io/**", lambda r: r.fulfill(status=200, content_type="text/html", body=html))
    page.route("http://localhost:8001/**", lambda r: r.fulfill(status=200, content_type="application/json", headers={"access-control-allow-origin": "*"}, body="{}"))
    page.goto("https://plexifire.github.io/music-player/")
    page.wait_for_selector("#libBtn")
    page.evaluate("""() => { const d = document.createElement('div'); d.id = 'probe';
        d.innerHTML = '<img src="/api/x.jpg"><a href="/api/y.mp4">y</a><a href="https://example.com/z">z</a>'; document.body.appendChild(d); }""")
    page.wait_for_function("() => document.querySelector('#probe img').getAttribute('src').startsWith('http://localhost:8001/api/')")
    assert page.get_attribute("#probe a:nth-of-type(1)", "href") == "http://localhost:8001/api/y.mp4"
    assert page.get_attribute("#probe a:nth-of-type(2)", "href") == "https://example.com/z"          # others are left alone


def test_on_github_pages_every_request_for_the_mac_goes_to_the_mac_and_the_clock_does_not_flicker(page, server):
    html = (Path(__file__).resolve().parents[2] / "server" / "static" / "index.html").read_text()
    seen = []
    page.route("https://plexifire.github.io/**", lambda r: r.fulfill(status=200, content_type="text/html", body=html))
    page.route("http://localhost:8001/**", lambda r: (seen.append(r.request.url), r.fulfill(status=200, content_type="application/json", headers={"access-control-allow-origin": "*"},
               body='{"on":true,"busy":false,"message":"Waiting: it works only when a song has to be fetched","mode":"local","connected":false}')))
    page.goto("https://plexifire.github.io/music-player/")
    page.wait_for_function("() => document.querySelector('#helperMsg').textContent.startsWith('Connected to your Mac for')", timeout=15000)
    texts = []
    for _ in range(12):                                         # over several seconds the text must never fall back to the other message
        texts.append(page.inner_text("#helperMsg"))
        page.wait_for_timeout(500)
    assert all(t.startswith("Connected to your Mac for") for t in texts), texts
    page.evaluate("() => { const a = new Audio(); a.src = BASE + '/api/projects/x/level-demo?i=1'; return fetch(BASE + '/api/projects/x/tracks/1/peaks?points=600'); }")
    page.wait_for_timeout(500)
    assert any("/peaks?points=600" in u for u in seen) and all(u.startswith("http://localhost:8001/") for u in seen)
