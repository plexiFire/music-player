# Senora in the cloud

## How the pieces fit
- **Hosted page** (Docker image, `SENORA_MODE=cloud`): the web page, your playlists, and the songs your computer uploads.
  It never contacts YouTube. It asks for a password (`SENORA_PASSWORD`); without one it shows nothing.
- **Helper on your computer** (`./start_senora helper https://your-page`): connects OUT to the page, so nothing is opened on your router.
  It fetches songs only when the page asks, uploads them, keeps its own copies in `~/.senora_helper/work/<playlist>` until that playlist
  is finished, then deletes only those folders.

## Connect your computer
1. Open the hosted page, press **Connect my computer**: it shows a one-time code (valid 10 minutes).
2. On your computer run `./start_senora helper https://your-page` and type the code. The helper keeps a token in `~/.senora_helper/config.json`
   (only a hash is stored on the page). **Disconnect** on the page revokes it.
3. Add links on the page and press Extract: each song shows "fetching" with the time, then appears with its cover.

## Deploy the page (any host that runs a Docker image)
Set these environment variables on the host: `SENORA_PASSWORD` (required), `SENORA_CONTACT_EMAIL`, `GROQ_API_KEY` (optional).
Mount a persistent disk at `/data`. Free hosts that sleep or wipe their disk lose playlists: check the host's free-tier rules first.

## What is not done yet
- **Rendering the video in the cloud.** The hosted page cannot render (free hosts are too small). GitHub Actions can (`build-playlist`),
  but it needs the songs, and they live on the hosted page. The missing link is handing the uploaded songs to the workflow
  (a storage bucket, for example) and starting it from the page. This needs your storage bucket and a GitHub token set as secrets.
- YouTube blocks GitHub's servers, so downloading in Actions does not work (`yt-diagnose` shows this). That is why songs go through the helper.
