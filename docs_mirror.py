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
import time
from pathlib import Path

import requests

ROOT = Path(__file__).parent
REPO = os.environ.get("GITHUB_REPOSITORY", "nickrogers280-coder/jc-board-tracker")
TAG = "documents"
API = "https://jerseycitynj-energovpub.tylerhost.net/apps/selfservice/api/"
HDR = {"tenantId": "1", "tenantName": "JerseyCityNJProd", "Tyler-TenantUrl": "JerseyCityNJProd", "Tyler-Tenant-Culture": "en-US",
       "FileToken": "", "DownloadProvider": "attachment", "FileType": "attachment", "AllowViewCorrection": "false",
       "User-Agent": "Mozilla/5.0 (JC Board Tracker)"}
CHUNK = 20_000_000  # same chunk size the portal itself uses
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


def warm(sess):
    """Load the portal page once so the session carries the portal's cookies (server affinity)."""
    sess.cookies.clear()
    try:
        sess.get("https://jerseycitynj-energovpub.tylerhost.net/apps/selfservice/JerseyCityNJProd", headers={"User-Agent": HDR["User-Agent"]}, timeout=60)
        sess.get(API + "energov/search/criteria", headers=HDR, timeout=60)
    except requests.RequestException:
        pass


def gh(*args, check=True):
    return subprocess.run(["gh", *args], check=check, capture_output=True, text=True)


RELEASE_CAP = 990  # GitHub allows 1,000 files per release; new files go to one release per filing year


class Releases:
    """The original `documents` release (full) plus `documents-<year>` (then -<year>-2, ...) for everything after."""

    def __init__(self):
        self.names = {}

    def load(self, tag):
        if tag not in self.names:
            if gh("release", "view", tag, "-R", REPO, check=False).returncode != 0:
                gh("release", "create", tag, "-R", REPO, "--title", f"Case documents ({tag})",
                   "--notes", "Current version of each document filed on tracked Jersey City Planning/Zoning Board cases. Updated automatically.")
                self.names[tag] = {}
            else:
                assets = json.loads(gh("release", "view", tag, "-R", REPO, "--json", "assets").stdout).get("assets") or []
                self.names[tag] = {x["name"]: x.get("size") for x in assets}
        return self.names[tag]

    def find(self, name, year):
        for tag in [TAG] + self.tags(year):
            if name in self.load(tag):
                return tag, self.names[tag][name]
        return None, None

    def tags(self, year):
        out, n = [f"{TAG}-{year}"], 2
        while len(self.load(out[-1])) >= RELEASE_CAP:
            out.append(f"{TAG}-{year}-{n}")
            n += 1
        return out

    def target(self, year):
        return self.tags(year)[-1]


def case_year(case):
    m = re.match(r"[PZ](\d{4}|\d{2})-", case or "")
    if not m:
        return "other"
    y = int(m.group(1))
    return y + 2000 if y < 100 else y


def main():
    cases = json.loads((ROOT / "raw/jc_cases.json").read_text())["cases"]
    # Newest filings first, so a backlog never holds back the documents people look at most.
    cases.sort(key=lambda c: (c.get("status") or "").lower() in ("approved", "denied", "withdrawn", "void", "closed", "expired"))
    cases.sort(key=lambda c: c.get("applied") or "", reverse=True)
    mpath = ROOT / "data/mirror.json"
    mirror = json.loads(mpath.read_text()) if mpath.exists() else {}
    rel = Releases()

    want = {}
    for c in cases:
        for kind, d in current_versions(c.get("docs") or []).items():
            if d.get("id"):
                want[d["id"]] = (c["id"], d, kind)
    # Kushner / KRE portfolio buildings: current documents of every case on those lots.
    pf = ROOT / "raw/portfolio.json"
    for bld in (json.loads(pf.read_text()) if pf.exists() else []):
        for pc in bld.get("cases") or []:
            for kind, d in current_versions(pc.get("docs") or []).items():
                if d.get("id") and d["id"] not in want:
                    want[d["id"]] = (pc["id"], d, kind)
    # Earlier approvals that tracked cases extend or amend: their current documents too.
    ppath = ROOT / "raw/priors.json"
    for ref, p in (json.loads(ppath.read_text()) if ppath.exists() else {}).items():
        for kind, d in current_versions(p.get("docs") or []).items():
            if d.get("id") and d["id"] not in want:
                want[d["id"]] = (ref, d, kind)

    added = failed = 0
    s = requests.Session()
    warm(s)
    budget = int(os.environ.get("MIRROR_MAX_FILES", "400"))  # spread big backlogs over several runs
    for aid, (case, d, kind) in want.items():
        name = asset_name(case, d)
        if aid in mirror and mirror[aid]["asset"] in rel.load(mirror[aid].get("tag", TAG)):
            continue
        year = case_year(case)
        tag, size0 = rel.find(name, year)
        if tag:  # already on a release (e.g. a run whose record didn't get saved): just record it
            mirror[aid] = {"asset": name, "size": size0 or 0, "case": case, "kind": kind, "tag": tag}
            continue
        try:
            size = None
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / name
                for attempt in range(6):
                    try:
                        # The portal keeps a file ready on the server that answered the metadata call; ask again and
                        # re-download from the start if a chunk lands on a different server.
                        mj = s.get(API + "energov/attachments/metadata/", headers={**HDR, "FileID": aid}, timeout=60).json()
                        meta = mj.get("Result")
                        if not meta:
                            raise RuntimeError("portal did not return the file: " + str(mj.get("ErrorMessage") or "no details"))
                        size = int(meta["FileSize"])
                        if size > MAX_BYTES:
                            break
                        tok = meta.get("FileToken") or ""
                        with open(path, "wb") as fh:
                            got = 0
                            while got < size:
                                end = min(got + CHUNK, size) - 1
                                r = s.get(API + "/energov/attachments/rangedownload/", headers={**HDR, "FileID": aid, "FileToken": tok, "range": f"bytes={got}-{end}"}, timeout=180)
                                r.raise_for_status()
                                if not r.content:
                                    raise RuntimeError("empty chunk")
                                fh.write(r.content)
                                got += len(r.content)
                        break
                    except Exception:
                        if attempt == 5:
                            raise
                        time.sleep(5 * (attempt + 1))  # back off: the portal throttles bursts of downloads
                        if attempt in (2, 4):
                            warm(s)
                if size and size > MAX_BYTES:
                    print("too large for a release asset, skipped:", case, d["name"], size)
                    continue
                tag = rel.target(year)
                gh("release", "upload", tag, str(path), "-R", REPO, "--clobber")
            mirror[aid] = {"asset": name, "size": size, "case": case, "kind": kind, "tag": tag}
            rel.names[tag][name] = size
            added += 1
            time.sleep(0.6)
            if added >= budget:
                print(f"reached {budget} new files this run; the rest follow on the next runs")
                break
            print(f"mirrored {case} {kind}: {d['name']} ({size/1e6:.1f} MB)")
        except Exception as e:
            failed += 1
            print("mirror failed", case, d["name"], e, file=sys.stderr)

    # Drop copies that a newer version has replaced, so the release only holds current files.
    removed = 0
    for aid in [a for a in mirror if a not in want]:
        gh("release", "delete-asset", mirror[aid].get("tag", TAG), mirror[aid]["asset"], "-R", REPO, "-y", check=False)
        del mirror[aid]
        removed += 1

    mpath.write_text(json.dumps(mirror, indent=0, sort_keys=True))
    print(f"documents: {len(want)} current, {added} new, {removed} replaced, {failed} failed")


if __name__ == "__main__":
    main()
