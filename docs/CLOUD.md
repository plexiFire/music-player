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

## Oracle Cloud Always Free VM: step by step
The page AND the video rendering both run on the VM, so no GitHub Actions, bucket or token is needed. YouTube blocks data-centre addresses
(GitHub's, and very likely Oracle's too), so songs still come through the helper on your Mac.

1. **Account.** Sign up at oracle.com/cloud/free. A card is asked for identity checks; stay on the Always Free plan and do not upgrade. Pick your
   home region carefully: it cannot be changed, and some regions often have no free Arm capacity.
2. **Make the VM.** Compute > Instances > Create. Image: Ubuntu (aarch64). Shape: Ampere A1 Flex, up to 4 cores and 24 GB (the free size may be smaller now:
   use what Oracle shows as free). Boot volume 100-150 GB (the free total is 200 GB). Add your SSH public key (`ssh-keygen -t ed25519` on your Mac,
   then paste `~/.ssh/id_ed25519.pub`). If it says "out of capacity", try again later or another availability domain.
3. **Open the doors.** In the VM's network (VCN > Security List) add Ingress rules for TCP 80 and 443 from 0.0.0.0/0.
4. **A free address.** At duckdns.org (sign in with GitHub or Google) make a name such as `myname.duckdns.org` and set its IP to the VM's public IP.
5. **Log in and deploy.**
   ```
   ssh ubuntu@<the VM's public IP>
   git clone https://github.com/plexiFire/music-player.git senora && cd senora
   ./deploy/oracle-setup.sh
   ```
   It asks for the address, a password for the page and your contact e-mail. It installs Docker, builds and starts Senora, and adds HTTPS.
6. **Open** `https://myname.duckdns.org`, type the password (any user name), press **Connect my computer**.
7. **On your Mac, once:** `./start_senora install-helper`. From then on the Connect button starts the helper.
8. **Update later:** `ssh` in, `cd senora && git pull && ./deploy/oracle-setup.sh` (playlists in `/var/senora-data` are kept).

## Things to know about the free VM
- Oracle can reclaim an Always Free VM that stays idle (CPU very low for 7 days). Renders and use keep it busy, but a long break may not. Check the VM now and then.
- Back up `/var/senora-data` (for example `scp -r` it to your Mac now and then): there is no second copy.
- The price of "free" is that Oracle's terms can change; look at your Oracle console now and then.
