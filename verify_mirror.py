"""Check the document copies on the GitHub releases and drop broken ones so docs_mirror.py copies them again.

Some early copies came back from the city portal holding a different file's bytes cut to the right size. They start
like a PDF but never finish. This reads the first and last few KB of every copy (HTTP range requests, no full
download), and removes copies that aren't intact: the asset is deleted and its record dropped from data/mirror.json.
Copies already checked are remembered in raw/mirror_verified.json, so later runs only check new ones.
"""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).parent
REPO = os.environ.get("GITHUB_REPOSITORY", "nickrogers280-coder/jc-board-tracker")
BASE = f"https://github.com/{REPO}/releases/download/"


def check(item):
    aid, m = item
    url = BASE + m.get("tag", "documents") + "/" + m["asset"]
    try:
        s = requests.Session()
        head = s.get(url, headers={"Range": "bytes=0-7"}, timeout=60).content[:8]
        n = int(m.get("size") or 0)
        r = s.get(url, headers={"Range": f"bytes={max(0, n - 4096)}-{max(0, n - 1)}"}, timeout=60)  # suffix ranges aren't supported
        if r.status_code not in (200, 206):
            return aid, None, f"HTTP {r.status_code}"
        tail = r.content
    except Exception as e:
        return aid, None, str(e)
    if head.startswith(b"%PDF"):
        ok = b"%%EOF" in tail
    elif head.startswith(b"PK"):
        ok = b"PK\x05\x06" in tail
    else:
        ok = bool(head)
    return aid, ok, ""


def main():
    mpath = ROOT / "data/mirror.json"
    mirror = json.loads(mpath.read_text())
    vpath = ROOT / "raw/mirror_verified.json"
    done = json.loads(vpath.read_text()) if vpath.exists() else {}
    todo = [(a, m) for a, m in mirror.items() if done.get(a) != m["asset"]]
    print(f"checking {len(todo)} of {len(mirror)} document copies")
    bad = []
    with ThreadPoolExecutor(12) as ex:
        for aid, ok, err in ex.map(check, todo):
            if ok is None:
                continue  # network trouble: check again next run
            if ok:
                done[aid] = mirror[aid]["asset"]
            else:
                bad.append(aid)
    for aid in bad:
        m = mirror.pop(aid)
        subprocess.run(["gh", "release", "delete-asset", m.get("tag", "documents"), m["asset"], "-R", REPO, "-y"], capture_output=True)
        done.pop(aid, None)
    mpath.write_text(json.dumps(mirror, indent=0, sort_keys=True))
    vpath.write_text(json.dumps(done))
    print(f"document copies: {len(bad)} broken removed (they will be copied again), {len(done)} verified")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("verification skipped:", e, file=sys.stderr)
