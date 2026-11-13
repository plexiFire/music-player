"""Groq LLM titles (OpenAI-compatible chat API). Needs GROQ_API_KEY; GROQ_MODEL optional."""
import json
import os
import re

import requests

URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"
PREFER = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
NOT_CHAT = ("whisper", "orpheus", "guard", "safeguard", "tts")


ENV_FILE = os.path.join(os.path.dirname(__file__), "..", "..", ".env")   # senora/.env


def _env_files():
    """Where a key may live: the file named by SENORA_ENV, then senora/.env next to this code."""
    return [f for f in (os.environ.get("SENORA_ENV"), ENV_FILE) if f]


def _env(name):
    """Environment variable first, then a line NAME=value in the first .env file that has it."""
    if os.environ.get(name):
        return os.environ[name]
    for path in _env_files():
        try:
            for line in open(path):
                k, _, v = line.strip().partition("=")
                if k.strip() == name and v.strip():
                    return v.strip().strip("'\"")
        except OSError:
            continue
    return None


def available():
    return bool(_env("GROQ_API_KEY"))


def prompt(ctx, n):
    p = ctx.get("patterns", {})
    style_rule = ("6) Start every title with '[Playlist] ' followed by a short, natural mood phrase in Title Case. "
                  "Good examples of the style (do not copy them): '[Playlist] Songs for a Slow Evening', "
                  "'[Playlist] Songs to Slow Down With', '[Playlist] Songs for a Quiet Night'. "
                  "7) After the '[Playlist]' prefix never use the word 'playlist' again. "
                  "8) Do not stuff artist names: mention an artist in at most two of the titles, and never more than two names. "
                  "9) Each title must read like something a person would click, with a different angle each time "
                  "(a feeling, a moment, an invitation). "
                  "10) Use ONLY the mood words given above. Do not invent other moods, genres or times of day "
                  "(no sunset, twilight, night, drive, study, sleep, acoustic, indie, calm... unless given). "
                  "11) Keep them short and simple, 30-55 characters, like '[Playlist] Songs for a Slow Evening'.\n" if ctx.get("prefer_bracket") else "")
    return (
        f"Write {n} YouTube titles for a music playlist video.\n"
        f"Playlist theme: {ctx['theme']}\n"
        f"Songs/artists in it: {', '.join(ctx.get('tracks_text', [])[:12]) or 'n/a'}\n"
        f"Mood: {ctx.get('mood') or 'n/a'}\n"
        f"Genre (may be named in titles): {ctx.get('genre') or 'n/a'}\n"
        f"Phrases people search: {', '.join(ctx.get('suggestions', [])[:10]) or 'n/a'}\n"
        f"Keywords in top-performing similar videos: {', '.join(ctx.get('keywords', [])[:12]) or 'n/a'}\n"
        f"Typical top title length: {p.get('median_len', 'n/a')} chars. Examples of what performs (style only, do not copy):\n"
        + "\n".join(f"- {t}" for t in p.get("examples", [])[:6]) + "\n"
        f"Do NOT resemble these earlier titles:\n" + "\n".join(f"- {t}" for t in ctx.get("avoid", [])[:15]) + "\n\n"
        "Rules: 1) Must be TRUE to the playlist: only mention artists/songs listed above, and never claim a language, genre or mood not given above (e.g. do not say Hindi, Bollywood, R&B unless listed). 2) 40-70 characters, never over 100. "
        "3) Put the main keyword early. 4) No clickbait, no lies, no ALL CAPS shouting, at most one emoji. "
        "5) Make the titles clearly different from each other in structure and wording.\n"
        + style_rule +
        'Reply with JSON only: {"titles": ["...", "..."]}')


def parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        arr = json.loads(m.group(0))["titles"] if m else []
    except (ValueError, KeyError, TypeError):
        arr = re.findall(r'"([^"]{10,100})"', text or "")
    return [re.sub(r"\s+", " ", t).strip() for t in arr if isinstance(t, str) and t.strip()]


def pick_model(key):
    """Ask Groq which models this account can use; take the best chat model we know, else any chat model."""
    try:
        r = requests.get(URL.replace("/chat/completions", "/models"), headers={"Authorization": f"Bearer {key}"}, timeout=20)
        ids = [m["id"] for m in r.json().get("data", []) if m.get("active", True)]
    except (requests.RequestException, ValueError, KeyError):
        return None
    chat = [i for i in ids if not any(x in i for x in NOT_CHAT)]
    return next((m for m in PREFER if m in chat), chat[0] if chat else None)


def _call(key, model, ctx, n, timeout, json_mode=True):
    body = {"model": model, "temperature": 0.9,
            "messages": [{"role": "system", "content": "You are an expert YouTube music-channel title writer."},
                         {"role": "user", "content": prompt(ctx, n)}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    return requests.post(URL, headers={"Authorization": f"Bearer {key}"}, timeout=timeout, json=body)


def titles(ctx, n=10, timeout=60):
    """Returns (titles, warning). Never raises: LLM trouble just means template titles only."""
    key = _env("GROQ_API_KEY")
    if not key:
        return [], "Groq key not found (put GROQ_API_KEY in the .env file next to the code, or set SENORA_ENV): used data-filled templates only"
    try:
        model = _env("GROQ_MODEL") or DEFAULT_MODEL
        r = _call(key, model, ctx, n, timeout)
        if r.status_code == 404 or (r.status_code == 400 and "model" in r.text.lower()):
            alt = pick_model(key)                      # configured model not available on this account
            if alt and alt != model:
                model, r = alt, _call(key, alt, ctx, n, timeout)
        if r.status_code == 400 and any(x in r.text for x in ("response_format", "validate JSON", "failed_generation")):
            r = _call(key, model, ctx, n, timeout, json_mode=False)   # strict JSON mode rejected it: ask in plain mode
        if r.status_code != 200:
            return [], f"Groq error {r.status_code}: {r.text[:120]}"
        return parse(r.json()["choices"][0]["message"]["content"]), None
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        return [], f"Groq request failed: {e}"


def _chat(key, prompt_text, timeout=45, temperature=0.9, json_mode=False):
    body = {"model": _env("GROQ_MODEL") or DEFAULT_MODEL, "temperature": temperature,
            "messages": [{"role": "system", "content": "You are an expert YouTube music-channel title writer."},
                         {"role": "user", "content": prompt_text}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = requests.post(URL, headers={"Authorization": f"Bearer {key}"}, timeout=timeout, json=body)
    if r.status_code == 400 and json_mode:
        body.pop("response_format")
        r = requests.post(URL, headers={"Authorization": f"Bearer {key}"}, timeout=timeout, json=body)
    if r.status_code == 404:                         # configured model not on this account
        alt = pick_model(key)
        if alt:
            body["model"] = alt
            r = requests.post(URL, headers={"Authorization": f"Bearer {key}"}, timeout=timeout, json=body)
    return r


def style_titles(prompt_text):
    """Titles from the channel-style prompt. Returns (titles, warning); never raises."""
    key = _env("GROQ_API_KEY")
    if not key:
        return [], "Groq key not found: used the channel's own title bank only"
    try:
        r = _chat(key, prompt_text, json_mode=True)
        if r.status_code != 200:
            return [], f"Groq error {r.status_code}: {r.text[:120]}"
        return parse(r.json()["choices"][0]["message"]["content"]), None
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        return [], f"Groq request failed: {e}"


def sentence(prompt_text):
    """One short generated sentence, or None."""
    key = _env("GROQ_API_KEY")
    if not key:
        return None
    try:
        r = _chat(key, prompt_text, temperature=0.7)
        if r.status_code != 200:
            return None
        t = re.sub(r"\s+", " ", r.json()["choices"][0]["message"]["content"]).strip().strip("\"'")
        return t if 8 <= len(t) <= 140 and not re.search(r"[^\x00-\u024f\u2019\u2014]", t) else None
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return None
