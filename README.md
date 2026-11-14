# Senora

## Setup (once)
```
cd senora-git
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt            # needs ffmpeg installed (macOS: brew install ffmpeg)
cp .env.example .env                       # then put your GROQ_API_KEY and SENORA_CONTACT_EMAIL in .env
```

## Run the web page
```
python -m uvicorn server.app:app --port 8001 --reload --reload-dir server --reload-dir engine
```
Open http://localhost:8001

## Command line
```
python -m engine.cli import "<youtube link>" --project work/p.json --title "My playlist" --authorized
python -m engine.cli import --file links.txt --project work/p.json --authorized     # one link per line
python -m engine.cli trim work/p.json                                                # suggestions only
python -m engine.cli trim work/p.json --track 2 --start 0 --end 187.7                # cut by hand
python -m engine.cli trim work/p.json --track 2 --restore                            # undo
python -m engine.cli build work/p.json -o out/video.mp4                              # video, thumbnail, title, description
python -m engine.cli build work/p.json -o out/video.mp4 --preview                    # quick 720p
python -m engine.cli titles work/p.json                                              # title ideas only
python -m engine.cli thumb "<youtube link>" -o work/cover.png                        # save one video's thumbnail
python -m engine.cli download "<youtube link>" --authorized                          # audio only
```

## Cloud build (GitHub Actions)
```
python -m engine.cli cloud-build job.json --out out        # same as the workflow, on this computer
python scripts/cloud_check.py --minutes 3 --skip-youtube   # how long a render takes on this computer
```
On GitHub: Actions tab, `build-playlist`, paste the job file (page, last step, "Download job file for cloud build").
Secrets to add (Settings, Secrets and variables, Actions): `GROQ_API_KEY`, `SENORA_CONTACT_EMAIL`. Details: [docs/CLOUD.md](docs/CLOUD.md).

## Tests
```
python -m pytest -q                                                      # unit tests
pip install -r requirements-dev.txt && python -m playwright install chromium
python -m pytest -q tests/smoke                                          # browser smoke test
```
