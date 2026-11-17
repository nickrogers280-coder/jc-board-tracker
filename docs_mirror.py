"""Mirror the newest version of each case document to a GitHub release, so the map can link straight to the file.

The city portal only serves files to its own page script (the file ID travels in a request header), so a
plain link can't download them. This keeps one copy of the current version of each document type per case
as an asset on the release tagged `documents`, and records the links in data/mirror.json.

Run inside GitHub Actions (needs the `gh` CLI and GH_TOKEN). Reads raw/jc_cases.json from fetch.py.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

ROOT = Path(__file__).parent
REPO = os.environ.get("GITHUB_REPOSITORY", "nickrogers280-coder/jc-board-tracker")
TAG = "documents"
API = "https://jerseycitynj-energovpub.tylerhost.net/apps/selfservice/api/"
HDR = {"tenantId": "1", "tenantName": "JerseyCityNJProd", "Tyler-TenantUrl": "JerseyCityNJProd", "Tyler-Tenant-Culture": "en-US",
       "FileToken": "", "DownloadProvider": "attachment", "FileType": "attachment", "AllowViewCorrection": "false",
       "User-Agent": "Mozilla/5.0 (JC Board Tracker)"}
CHUNK = 8 * 1024 * 1024
MAX_BYTES = 1_900_000_000  # GitHub release assets top out at 2 GB

# Same document types the map shows; the newest file of each type per case is "the current version".
KINDS = [
    (r"site ?plan|architect|drawing|\bplans?\b|elevation|floor ?plan", "plans"), (r"survey", "survey"),
    (r"staff memo|staff report", "staff-memo"), (r"traffic", "traffic"), (r"storm ?water|drainage", "stormwater"),
    (r"render", "rendering"), (r"resolution|memorializ", "resolution"), (r"affordable|\bAH\b", "affordable"),
    (r"notice|proof of service|200.?f(oo)?t|affidavit", "notice"), (r"forestry", "forestry"), (r"jcmua", "jcmua"),
    (r"engineering", "engineering"), (r"fire", "fire"), (r"tax cert", "tax-cert"), (r"demolition", "demolition"),
    (r"application|checklist|zoning (chart|table)", "application"),
]


def kind_of(doc):
    t = f"{doc['name']} {doc.get('note', '')}"
    for pat, k in KINDS:
        if re.search(pat, t, re.I):
            return k
    # Unrecognized: treat files with the same name (ignoring dates, versions, revision marks) as versions of one document.
    stem = re.sub(r"\.[a-z0-9]{2,5}$", "", doc["name"].lower())
    stem = re.sub(r"\b(rev(ision)?|v|ver|version)\s*\.?\d+\b|\d{4}[-_.]\d{1,2}[-_.]\d{1,2}|\d{1,2}[-_.]\d{1,2}[-_.]\d{2,4}|\d{6,8}|\(\d+\)|[_\-\s]+", " ", stem)
    return "other:" + re.sub(r"\s+", " ", stem).strip()[:60]


def current_versions(docs):
    best = {}
    for d in docs:
        k = kind_of(d)
        if k not in best or (d.get("added") or "") > (best[k].get("added") or ""):
            best[k] = d
    return best


def asset_name(case, doc):
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", doc["name"]).strip("_")[:120] or "file"
    return f"{case}__{doc['id'][:8]}__{safe}"


def gh(*args, check=True):
    return subprocess.run(["gh", *args], check=check, capture_output=True, text=True)


def main():
    cases = json.loads((ROOT / "raw/jc_cases.json").read_text())["cases"]
    mpath = ROOT / "data/mirror.json"
    mirror = json.loads(mpath.read_text()) if mpath.exists() else {}

    if gh("release", "view", TAG, "-R", REPO, check=False).returncode != 0:
        gh("release", "create", TAG, "-R", REPO, "--title", "Case documents",
           "--notes", "Current version of each document filed on tracked Jersey City Planning/Zoning Board cases. Updated automatically.")
    assets = json.loads(gh("release", "view", TAG, "-R", REPO, "--json", "assets").stdout).get("assets") or []
    existing = {x["name"] for x in assets}

    want = {}
    for c in cases:
        for kind, d in current_versions(c.get("docs") or []).items():
            if d.get("id"):
                want[d["id"]] = (c["id"], d, kind)

    added = failed = 0
    s = requests.Session()
    for aid, (case, d, kind) in want.items():
        name = asset_name(case, d)
        if aid in mirror and mirror[aid]["asset"] in existing:
            continue
        try:
            meta = s.get(API + "energov/attachments/metadata/", headers={**HDR, "FileID": aid}, timeout=60).json()["Result"]
            size = int(meta["FileSize"])
            if size > MAX_BYTES:
                print("too large for a release asset, skipped:", case, d["name"], size)
                continue
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / name
                with open(path, "wb") as fh:
                    got = 0
                    while got < size:
                        end = min(got + CHUNK, size) - 1
                        r = s.get(API + "/energov/attachments/rangedownload/", headers={**HDR, "FileID": aid, "range": f"bytes={got}-{end}"}, timeout=180)
                        r.raise_for_status()
                        fh.write(r.content)
                        got += len(r.content)
                        if not r.content:
                            raise RuntimeError("empty chunk")
                gh("release", "upload", TAG, str(path), "-R", REPO, "--clobber")
            mirror[aid] = {"asset": name, "size": size, "case": case, "kind": kind}
            existing.add(name)
            added += 1
            print(f"mirrored {case} {kind}: {d['name']} ({size/1e6:.1f} MB)")
        except Exception as e:
            failed += 1
            print("mirror failed", case, d["name"], e, file=sys.stderr)

    # Drop copies that a newer version has replaced, so the release only holds current files.
    removed = 0
    for aid in [a for a in mirror if a not in want]:
        gh("release", "delete-asset", TAG, mirror[aid]["asset"], "-R", REPO, "-y", check=False)
        del mirror[aid]
        removed += 1

    mpath.write_text(json.dumps(mirror, indent=0, sort_keys=True))
    print(f"documents: {len(want)} current, {added} new, {removed} replaced, {failed} failed")


if __name__ == "__main__":
    main()
