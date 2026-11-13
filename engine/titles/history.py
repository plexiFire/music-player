"""Remember offered titles so one playlist's titles never repeat another's."""
import json
import os
import re
from datetime import date


def _tok(s):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def similarity(a, b):
    ta, tb = _tok(a), _tok(b)
    return len(ta & tb) / max(1, len(ta | tb))


def load(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return []


def titles(path):
    return [h["title"] for h in load(path)]


def record(path, new_titles, project=""):
    if not path:
        return
    items = load(path)
    have = {h["title"] for h in items}
    items += [{"title": t, "project": project, "date": date.today().isoformat()} for t in new_titles if t not in have]
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    json.dump(items, open(path, "w"), indent=1, ensure_ascii=False)
