"""Ownership and sales history for tracked lots.

Two public sources, joined by deed book/page:
  - Hudson County Register of Deeds index (acclaim.hcnj.us): every recorded deed and mortgage on a block/lot, with
    grantor (seller / borrower) and grantee (buyer / lender) names and the recording date.
  - NJ Division of Taxation SR1A sales file (2020 on): sale price, deed date and usable/non-usable code for every
    recorded deed. Names are blanked statewide in this file, which is why the county index supplies them.

Writes raw/sales.json: {pams_pin: [records...]}. Lots are refreshed every 30 days; new lots right away.
"""
import datetime as dt
import io
import json
import re
import sys
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).parent
ACCLAIM = "https://acclaim.hcnj.us/AcclaimWeb/"
SR1A = "https://www.nj.gov/treasury/taxation/lpt/statdata/"
TODAY = dt.date.today()
UA = {"User-Agent": "Mozilla/5.0 (JC Board Tracker; public records lookup)"}
KEEP = re.compile(r"^(DEED|MORTGAGE|MASTER DEED|ASSIGNMENT OF MORTGAGE)", re.I)

# State non-usable codes worth showing next to a price (N.J.A.C. 18:12-1.1).
NU = {"1": "related parties", "2": "related parties", "3": "nominal/less than $100", "4": "partial interest", "5": "estate sale",
      "6": "court order / sheriff", "7": "foreclosure / bank", "8": "liquidation", "9": "lender sale", "10": "family sale",
      "12": "multiple parcels", "13": "corporate", "18": "foreclosure / REO", "26": "multiple lots", "28": "change in property after sale",
      "29": "lease-related", "30": "auction", "31": "partial", "33": "other"}


# ------------------------------------------------------------------ state sales file
def sr1a_index(years):
    """{(block, lot): [sale, ...]} for Jersey City from the state sales files. Past years are cached."""
    idx = {}
    for y in years:
        cache = ROOT / f"raw/sr1a_{y}.json"
        recs = None
        if cache.exists() and y < TODAY.year - 1:
            recs = json.loads(cache.read_text())
        if recs is None:
            name = f"Sales{y}.zip"
            try:
                r = requests.get(SR1A + name, timeout=300, headers=UA)
                r.raise_for_status()
            except Exception as e:
                print("sales file not available:", name, e, file=sys.stderr)
                recs = json.loads(cache.read_text()) if cache.exists() else []
            else:
                recs = parse_sr1a(r.content)
                cache.write_text(json.dumps(recs))
        for s in recs:
            for bl in s["lots"]:
                idx.setdefault(tuple(bl), []).append(s)
    # Year-to-date file (current year, still being filled in)
    try:
        r = requests.get(SR1A + f"YTDSR1A{TODAY.year + 1}.zip", timeout=300, headers=UA)
        if r.ok:
            for s in parse_sr1a(r.content):
                for bl in s["lots"]:
                    idx.setdefault(tuple(bl), []).append(s)
    except Exception:
        pass
    return idx


def _num(s):
    s = s.strip().lstrip("0")
    return s or "0"


def _lot(lot, sfx):
    lot, sfx = _num(lot), sfx.strip().lstrip("0")
    return f"{lot}.{sfx.rjust(2, '0')}" if sfx else lot


def _date6(s, order="mdy"):
    s = s.strip()
    if len(s) != 6 or not s.isdigit():
        return None
    a, b, c = int(s[0:2]), int(s[2:4]), int(s[4:6])
    m, d, y = (a, b, c) if order == "mdy" else (b, c, a)
    y += 2000 if y < 50 else 1900
    try:
        return dt.date(y, m, d).isoformat()
    except ValueError:
        return None


def parse_sr1a(zbytes):
    out = []
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        for name in z.namelist():
            with z.open(name) as fh:
                for raw in io.TextIOWrapper(fh, encoding="latin-1", errors="replace"):
                    if not raw.startswith("0906"):
                        continue
                    L = raw.rstrip("\r\n").ljust(664)
                    block = _num(L[350:355]) + ("." + L[355:359].strip().lstrip("0") if L[355:359].strip().strip("0") else "")
                    lots = [[block, _lot(L[359:364], L[364:368])]]
                    for g in range(5):
                        o = 369 + g * 50
                        b2, l2 = L[o:o + 9].strip(), L[o + 9:o + 18].strip()
                        if b2 and l2:
                            lots.append([_num(b2.split(".")[0]) + ("." + b2.split(".")[1].lstrip("0") if "." in b2 and b2.split(".")[1].strip("0") else ""),
                                         _num(l2.split(".")[0]) + ("." + l2.split(".")[1].rjust(2, "0") if "." in l2 and l2.split(".")[1].strip("0") else "")])
                    price = int(L[37:46] or 0) if L[37:46].strip().isdigit() else None
                    out.append({
                        "lots": lots, "price": price, "deed_date": _date6(L[338:344]), "recorded": _date6(L[344:350]),
                        "book": L[328:333].strip().lstrip("0"), "page": L[333:338].strip().lstrip("0"),
                        "usable": L[33:34] == "U", "nu": (L[34:37].strip().lstrip("0") or L[637:640].strip().lstrip("0")),
                        "cls": L[626:628].strip(), "loc": L[297:322].strip(),
                    })
    return out


# ------------------------------------------------------------------ county deed index
class Deeds:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(UA)
        self.ok = False

    def start(self):
        try:
            self.s.get(ACCLAIM + "search/SearchTypeDocLegal", timeout=60)
            # The search is behind a usage disclaimer (data provided as-is); accepted on the account owner's instruction.
            self.s.post(ACCLAIM + "Search/Disclaimer?st=/AcclaimWeb/search/SearchTypeDocLegal", data={"disclaimer": "true"}, timeout=60)
            self.ok = True
        except Exception as e:
            print("county deed search unavailable:", e, file=sys.stderr)

    def lookup(self, block, lot):
        form = {"DateRangeList": " ", "RecordDateFrom": "1/1/1950", "RecordDateTo": TODAY.strftime("%-m/%-d/%Y"), "Block": block,
                "Lot": lot.split(".")[0], "LotFilter": "1", "SubdivisionFilter": "0", "TownshipFilter": "0", "CondoFilter": "0",
                "BookTypesDisplay": "All", "BookTypes": "All"}
        h = {"X-Requested-With": "XMLHttpRequest"}
        self.s.post(ACCLAIM + "search/SearchTypeDocLegal?Length=6", data=form, headers=h, timeout=60)
        rows, page = [], 1
        while True:
            j = self.s.post(ACCLAIM + "Search/GridResults", data={"page": page, "size": 500, "orderBy": "~", "groupBy": "~", "filter": "~"},
                            headers=h, timeout=90).json()
            rows += j.get("data") or []
            if len(rows) >= (j.get("total") or 0) or page >= 6:
                break
            page += 1
        out = []
        for x in rows:
            legal = x.get("DocLegalDescription") or ""
            if not on_lot(legal, block, lot) or not KEEP.search(x.get("DocTypeDescription") or ""):
                continue
            ms = re.search(r"\((\d+)\)", str(x.get("RecordDate") or ""))
            when = dt.datetime.utcfromtimestamp(int(ms.group(1)) / 1000).date().isoformat() if ms else None
            bp = (x.get("BookPage") or "").strip()
            out.append({"recorded": when, "type": (x.get("DocTypeDescription") or "").title(), "from": (x.get("DirectName") or "").strip(),
                        "to": (x.get("IndirectName") or "").strip(), "bookpage": bp, "instrument": x.get("InstrumentNumber"),
                        "legal": re.sub(r"\s+", " ", legal).strip()[:160]})
        return out


def _lots_in(legal):
    m = re.search(r"Lots?\s*:?\s*(.*?)\s*T?Blk", legal, re.I)
    return set(re.findall(r"\d+(?:\.\d+)?", m.group(1))) if m else set()


def on_lot(legal, block, lot):
    bm = re.search(r"T?Blk\s*:?\s*(\d+(?:\.\d+)?)", legal, re.I)
    if not bm or _num(bm.group(1).split(".")[0]) != _num(block.split(".")[0]):
        return False
    if not re.search(r"Municipality\s*:?\s*0906|JERSEY CITY", legal, re.I):
        return False
    want = {lot, lot.rstrip("0").rstrip(".") if "." in lot else lot}
    have = _lots_in(legal)
    return bool(want & have) or bool({w.split(".")[0] for w in want if "." not in w} & {h for h in have if "." not in h})


# ------------------------------------------------------------------ main
def build(pins):
    path = ROOT / "raw/sales.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    stale = TODAY.fromordinal(TODAY.toordinal() - 30).isoformat()
    todo = [p for p in sorted(set(pins)) if p and p.count("_") >= 2 and (p not in data or data[p].get("checked", "") < stale)]
    budget = 400
    if todo:
        d = Deeds()
        d.start()
        for i, pin in enumerate(todo[:budget]):
            _, blk, lot = pin.split("_", 2)
            lot = lot.split("_")[0]
            try:
                recs = d.lookup(blk, lot) if d.ok else None
            except Exception as e:
                print("deed lookup failed", pin, e, file=sys.stderr)
                recs = None
                time.sleep(5)
            if recs is not None:
                data[pin] = {"checked": TODAY.isoformat(), "deeds": recs}
            time.sleep(1.2)
            if i % 50 == 0:
                print(f"  deeds {i}/{min(len(todo), budget)}")
    idx = sr1a_index(range(2020, TODAY.year + 1))
    for pin in pins:
        if not pin or pin.count("_") < 2 or pin not in data:
            continue
        _, blk, lot = pin.split("_", 2)
        sales = idx.get((_num(blk.split(".")[0]), lot.split("_")[0]), [])
        data[pin]["sr1a"] = [{k: s[k] for k in ("price", "deed_date", "recorded", "book", "page", "usable", "nu", "cls")} | {"n_lots": len(s["lots"])} for s in sales]
    path.write_text(json.dumps(data))
    print(f"sales: {len(data)} lots on file, {len(todo)} looked up this run")
    return data


if __name__ == "__main__":
    cases = json.loads((ROOT / "raw/jc_cases.json").read_text())["cases"]
    pins = [l["pin"] for c in cases for l in (c.get("lots") or [])] + [c.get("pin") for c in cases]
    port = ROOT / "raw/portfolio.json"
    if port.exists():
        pins += [p for b in json.loads(port.read_text()) for p in b.get("pins", [])]
    build(pins)
