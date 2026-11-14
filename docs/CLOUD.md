# Running Senora in the cloud

Status: **phase 1 is ready to try** (heavy work on GitHub's computers, the page on your Mac). Phase 2 (the page hosted online,
YouTube upload, analytics) is **not built yet**: see [ROADMAP.md](../ROADMAP.md).

## What runs where

| part | phase 1 (now) | phase 2 (future) |
|---|---|---|
| the page (pick links, thumbnails, preview, edit text) | your Mac (`uvicorn`, see README) | a small always-on host with a login |
| the heavy build (download, 1080p render, thumbnails, title, description) | **GitHub Actions** (`build-playlist` workflow) | same, started from the page |
| the finished files | Actions artifact (7 days) or your Cloudflare R2 bucket | R2 + a database record |
| YouTube upload | by hand in YouTube Studio (A/B/C thumbnails are ready) | Approve button |

Why Actions: the repo is public, so standard runners are free. A job may run up to 6 hours, enough for a long 1080p render.
(Limits as I read them in GitHub's docs earlier; check the current numbers before you rely on them:
<https://docs.github.com/actions/administering-github-actions/usage-limits-billing-and-administration>.)

## Setup, step by step

1. **Push the code** to `plexiFire/music-player` (from the `senora-git` folder: `git push -u origin main`, with your plexiFire SSH key).
2. **Check Actions is on:** repo -> *Actions*. The `tests` workflow should start by itself and go green (unit tests + browser smoke test).
3. **Add secrets:** repo -> *Settings* -> *Secrets and variables* -> *Actions* -> *New repository secret*.

   | secret | needed? | what it is |
   |---|---|---|
   | `GROQ_API_KEY` | optional | your Groq key (better genre/mood, titles, hooks). Without it the channel's own title bank is used |
   | `SENORA_CONTACT_EMAIL` | recommended | the contact e-mail printed in the copyright part of the description. It is a secret on purpose: workflow inputs are public in a public repo |
   | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | optional | only if you want the files copied to Cloudflare R2 as well. Create a bucket and an *R2 API token* with write access in the Cloudflare dashboard |

   Never paste a key into the job file, an issue, or a commit. `.env` is git-ignored: keep it that way.
4. **Run the check once:** *Actions* -> *cloud-check* -> *Run workflow*. Read the summary at the bottom of the run:
   - *YouTube from this machine*: **OK** means downloads work from GitHub's computers. **BLOCKED** means YouTube refuses datacenter
     addresses: then build locally for now (the page on your Mac still works exactly as before) and see "If YouTube is blocked" below.
   - *Render speed*: the time a real 1080p render takes there, and a guess for a 20-minute video.
5. **Build a playlist:** on your Mac open the page, finish the playlist (links, mood, disc, background, 3 thumbnails) and on the last step
   press **Download job file for cloud build**. Then *Actions* -> *build-playlist* -> *Run workflow*, paste the file's contents, run.
   When it finishes: the run page shows the title and description, and the artifact `senora-<number>` holds the video, `thumbnail.jpg`,
   `thumbnail-A/B/C.jpg`, `description.txt`, `titles.txt` and `summary.json`.
6. **Upload** the video in YouTube Studio, use A/B/C in its thumbnail test, paste the description.

You confirm in the page ("I own or am licensed to use these songs") before a job file says `"authorized": true`. A job without it is refused.

## What to bring
- A GitHub account that can run Actions on `plexiFire/music-player` (you have it).
- Optional: a Groq API key, a Cloudflare account (R2), the e-mail you want in the copyright notice.
- Later (phase 2): a Google Cloud project with the YouTube Data API enabled and an OAuth client (done in your browser, no password is shared with this tool).

## If YouTube is blocked on the runner
- Keep building on your Mac (nothing changed there).
- Not built yet, only noted: a cookies option for yt-dlp (sensitive: it is your login) or a self-hosted runner at home.

## Costs and limits to keep an eye on
- Actions minutes: free for public repos. A private repo would use the monthly included minutes instead.
- Artifacts count against repo storage and are deleted after 7 days here. R2's free tier is 10 GB (as I read it earlier; check Cloudflare's current page).
- 3 videos a week is far below any limit I found. Many videos in parallel are not supported: one build at a time (the workflow queues them).

## Where to deploy phase 2 (not built, so only a plan)
The page itself is light (the heavy work stays on Actions), so a small always-on host is enough:
a Docker container on Fly.io or Render, or a cheap VPS. It needs: a login (so only you can use it), a place for `library.json` and the project
files (a persistent disk or a database + R2), and a GitHub token with *Actions: write* so the page can start `build-playlist` for you.
Do not host the page without a login: it can start builds on your account.
