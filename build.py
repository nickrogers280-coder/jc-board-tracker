"""Build data/map.json for the JC Board Tracker from the raw pulls.

Inputs (from the browser pull):
  raw/jc_cases_2026.json    - Jersey City permit portal (EnerGov) plan cases + NJOGIS parcel match + geocode
  raw/jc_agendas_2026.json  - parsed 2026 Planning Board / Zoning Board agendas (applicant, attorney, zone, hearing dates)
"""
import json, re, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
def _raw(name, legacy):
    p = ROOT / "raw" / name
    return json.loads((p if p.exists() else ROOT / "raw" / legacy).read_text(encoding="utf-8"))
cases_raw = _raw("jc_cases.json", "jc_cases_2026.json")
agendas = _raw("jc_agendas.json", "jc_agendas_2026.json")
_mp = ROOT / "data/mirror.json"
mirror = json.loads(_mp.read_text(encoding="utf-8")) if _mp.exists() else {}
RELEASE = "https://github.com/nickrogers280-coder/jc-board-tracker/releases/download/documents/"
_hp = ROOT / "data/history.json"
history = json.loads(_hp.read_text(encoding="utf-8")) if _hp.exists() else {}

WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}

PROP_CLASS = {"1": "Vacant land", "2": "Residential (1-4 fam.)", "4A": "Commercial", "4B": "Industrial", "4C": "Apartment (5+ units)",
              "15A": "Exempt - school", "15B": "Exempt - school", "15C": "Exempt - public", "15D": "Exempt - church/charity",
              "15E": "Exempt - cemetery", "15F": "Exempt - other", "5A": "Railroad", "5B": "Railroad", "3A": "Farm", "3B": "Farm"}


TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


def num(s):
    s = s.replace(",", "").strip().lower()
    if s.isdigit():
        return int(s)
    if "-" in s:
        a, _, b = s.partition("-")
        if a in TENS and b in WORDS and WORDS[b] < 10:
            return TENS[a] + WORDS[b]
        return None
    return WORDS.get(s, TENS.get(s))


def nums(pattern, text):
    out = []
    for m in re.finditer(pattern, text, re.I):
        v = num(m.group(1))
        if v is not None:
            out.append(v)
    return out


def parse_desc(d):
    d = d or ""
    t = re.sub(r"\s+", " ", d)
    # "(261) residential units", "87 residential units", "7-unit", "four (4) unit", "633 dwelling units"
    unit_pat = [
        r"\(?(\d[\d,]*|[a-z]+)\)?[\s-]*(?:new\s+)?(?:market[- ]rate\s+|residential\s+|dwelling\s+|multi-?family\s+|apartment\s+|rental\s+)*(?:dwelling\s+)?units?\b(?!\s*building\s+(?:storage|identification))",
        r"\(?(\d{1,4})\)?[\s-]*D\.\s?U\.",
    ]
    units = []
    for p in unit_pat:
        for m in re.finditer(p, t, re.I):
            v = num(m.group(1))
            ctx = t[max(0, m.start() - 25):m.end() + 15].lower()
            if v is None or v > 3000:
                continue
            if "storage unit" in ctx or "ami" in t[m.end():m.end() + 12].lower() or "accessory dwelling unit" in ctx and v <= 1:
                continue
            units.append(v)
    stories = nums(r"\((\d{1,2})\)[\s-]*stor(?:y|ies)\b", t) + nums(r"(?<![\d(])(\d{1,2})[\s-]*stor(?:y|ies)\b", t)
    if not stories:
        stories = nums(r"(?<![a-z-])([a-z]+(?:-[a-z]+)?)[\s-]*stor(?:y|ies)\b", t)
    stories = [v for v in stories if v and v <= 80]
    # Drop story counts that describe the building being demolished ("existing one-story building").
    keep = []
    for m in re.finditer(r"(?:\((\d{1,2})\)|(?<![\d(])(\d{1,2})|(?<![a-z-])([a-z]+(?:-[a-z]+)?))[\s-]*stor(?:y|ies)\b", t, re.I):
        v = num(m.group(1) or m.group(2) or m.group(3) or "")
        if v and v <= 80 and not re.search(r"existing\W*$", t[max(0, m.start() - 15):m.start()], re.I) and not re.search(r"^\W*(?:\w+\s){0,2}?(?:vacant|existing)", t[m.end():m.end() + 30], re.I):
            keep.append(v)
    if keep:
        stories = keep
    elif stories and len(stories) == 1 and stories[0] <= 2 and re.search(r"existing", t, re.I):
        stories = []
    parking = []
    for m in re.finditer(r"\(?(\d[\d,]*)\)?\s*((?:[\w-]+\s){0,3}?)parking spaces", t, re.I):
        if "bicycle" in m.group(2).lower() or "bike" in m.group(2).lower():
            continue
        v = num(m.group(1))
        if v is not None:
            parking.append(v)
    retail = nums(r"([\d,]{3,})\s*(?:\+/-\s*)?(?:sq\.?\s*ft\.?|square feet|sf)\s*(?:of\s+)?(?:ground[- ]floor\s+)?(?:retail|commercial)", t)
    retail += nums(r"(?:retail|commercial)(?:\s+space)?\s+(?:of\s+)?(?:approximately\s+)?([\d,]{3,})\s*(?:sq|sf|square)", t)
    aff = []
    aff += nums(r"(\d+)\)?\s*(?:of which\s+)?(?:are|shall be|will be|would be)?\s*(?:designated as\s+)?(?:deed[- ]restricted\s+)?affordable", t)
    aff += nums(r"(\d+)\)?\s+of which (?:are|will be|shall be|would be) (?:designated as )?affordable", t)
    aff += nums(r"\((\d+)\)\s*(?:residential\s+)?units\s+shall be set aside as\s+(?:deed[- ]restricted\s+)?affordable", t)
    aff += nums(r"\((\d+)\s+affordable", t)
    aff += nums(r"(\d+)\s+of which (?:are|will be|shall be) affordable", t)
    aff += nums(r"(\d+)\s+units\s*<\s*80%", t)
    aff = [a for a in aff if a < 2000]
    rooms = nums(r"(\d+)\s*(?:hotel\s+)?(?:guest\s+rooms|keys|hotel rooms)", t)
    return {
        "units": max(units) if units else None,
        "stories": max(stories) if stories else None,
        "parking": max(parking) if parking else None,
        "retail_sf": max(retail) if retail else None,
        "affordable": max(aff) if aff else None,
        "hotel_rooms": max(rooms) if rooms else None,
    }


def kind_of(ctype):
    t = ctype.split(" - ", 1)[1] if " - " in ctype else ctype
    if t == "Site Plan":
        return "new", "New site plan"
    if t.startswith("Site Plan Amendment"):
        return "amend", "Amendment"
    if "Extension" in t:
        return "ext", "Extension"
    if t.startswith("Subdivision"):
        return "subdiv", "Subdivision"
    if t.startswith("Variance"):
        return "variance", "Variance (no site plan)"
    if t.startswith("Appeal"):
        return "appeal", "Appeal / interpretation"
    if t.startswith("Signage"):
        return "sign", "Signage"
    if "Rezoning" in t or "Amendment /" in t:
        return "plan", "Plan / rezoning"
    return "other", t


def product_of(c, f, kind):
    d = (c.get("desc") or "").lower()
    if kind == "plan":
        return "plan"
    if kind == "sign" or re.search(r"\bantenna|cell (?:tower|site)|telecom|wireless|signage|\bsigns?\b", d) and not f["units"]:
        return "telecom"
    if re.search(r"warehouse|industrial|logistic|storage of building material|batching plant|self[- ]storage|distribution|manufactur", d) and not (f["units"] or 0) > 4:
        return "industrial"
    if f["units"] and f["units"] >= 5:
        return "multifamily"
    if f["units"] and f["units"] < 5:
        return "smallres"
    if re.search(r"multi-?family|mixed[- ]use|residential building|apartments?", d):
        return "multifamily"
    if re.search(r"hotel|retail|restaurant|office|commercial|fitness|school|medical|daycare|church|parking (?:lot|garage)|valet|store|golf|recreation|pier|gym", d):
        return "commercial"
    if kind == "subdiv" or re.search(r"subdivi|single[- ]family|two[- ]family|one[- ]family|dwelling|driveway|addition to the existing", d):
        return "smallres"
    return "other"


CLASS_PRODUCT = {"2": "smallres", "4C": "multifamily", "4A": "commercial", "4B": "industrial"}


def status_group(s):
    s = (s or "").lower()
    if s in ("approved", "complete", "approved with conditions"):
        return "approved"
    if s in ("denied",):
        return "denied"
    if s in ("withdrawn", "void"):
        return "closed"
    if "resolution" in s:
        return "heard"
    return "pending"


def clean_app(s):
    s = re.sub(r"\s+", " ", s or "").strip(" ,;")
    s = re.sub(r"\s*(Attorney|Review Planner|Address|Block|Zon(?:e|ing)|Ward).*$", "", s)
    return s


def norm_party(s):
    s = clean_app(s)
    s = re.sub(r",?\s*Esq\.?", "", s, flags=re.I).strip(" ,.")
    return s


def desc_applicant(d):
    m = re.search(r"filed by ([^(]+?)\s*\(the [\"“]?Applicant", d or "", re.I)
    return m.group(1).strip(" ,") if m else ""


out = []
by_mail = defaultdict(set)
for c in cases_raw["cases"]:
    p = c.get("parcel") or {}
    g = c.get("geo") or {}
    lat = p.get("lat") or (g.get("lat") if g and (g.get("score") or 0) >= 90 else None)
    lon = p.get("lon") or (g.get("lon") if g and (g.get("score") or 0) >= 90 else None)
    geo_src = "parcel" if p.get("lat") else ("address" if lat else None)
    f = parse_desc(c.get("desc"))
    kind, kind_label = kind_of(c["type"])
    ag = agendas.get(c["id"], {})
    hearings = sorted({(x[:10], "Zoning Board" if x.endswith("Z") else "Planning Board") for x in ag.get("dates", [])})
    applicant = clean_app(ag.get("app", "")) or desc_applicant(c.get("desc"))
    attorney = norm_party(ag.get("att", ""))
    pin = c.get("pin") or ""
    blk = p.get("PCLBLOCK") or (pin.split("_")[1] if pin.count("_") >= 2 else "")
    lot = p.get("PCLLOT") or (pin.split("_")[2] if pin.count("_") >= 2 else "")
    mail = ", ".join(x for x in [(p.get("ST_ADDRESS") or "").strip(), (p.get("CITY_STATE") or "").strip()] if x)
    addr = re.sub(r"\s+Jersey City NJ\s*\d{5}$", "", c.get("address") or "", flags=re.I).strip()
    addr = re.sub(r"\s+Unit:\s*\S+(\s+\S+)?$", "", addr)
    ward = (c.get("ward") or "").replace("WARD", "").strip()
    if ward.upper() == "NULL":
        ward = ""
    rec = {
        "id": c["id"],
        "case_id": c["caseId"],
        "board": "zoning" if c["id"].startswith("Z") else "planning",
        "type": c["type"],
        "kind": kind,
        "kind_label": kind_label,
        "status": c["status"],
        "status_group": status_group(c["status"]),
        "applied": (c.get("applied") or "")[:10],
        "expires": (c.get("expires") or "")[:10] or None,
        "completed": (c.get("completed") or "")[:10] or None,
        "ward": ward,
        "planner": c.get("planner") or "",
        "address": addr,
        "pams_pin": pin or None,
        "block": blk,
        "lot": lot,
        "zone": clean_app(ag.get("zone", "")),
        "applicant": applicant,
        "attorney": attorney,
        "hearings": hearings,
        "agenda_last": ag.get("last", ""),
        "desc": re.sub(r"\s+", " ", c.get("desc") or "").strip(),
        **f,
        "lat": round(lat, 6) if lat else None,
        "lon": round(lon, 6) if lon else None,
        "geo_source": geo_src,
        "prop_class": (p.get("PROP_CLASS") or "") or None,
        "class_label": PROP_CLASS.get(p.get("PROP_CLASS") or "", p.get("PROP_CLASS") or None),
        "prop_loc": p.get("PROP_LOC") or "",
        "land_val": p.get("LAND_VAL"),
        "imprvt_val": p.get("IMPRVT_VAL"),
        "net_value": p.get("NET_VALUE"),
        "calc_acre": p.get("CALC_ACRE"),
        "bldg_desc": (p.get("BLDG_DESC") or "").strip(),
        "yr_constr": p.get("YR_CONSTR") or None,
        "last_sale_price": p.get("SALE_PRICE") or None,
        "last_sale_date": None,
        "owner_mail": mail,
        "approval_expires": (c.get("approvalExpires") or "")[:10] or None,
        "docs": [dict({"name": d.get("name", ""), "note": d.get("note", ""), "added": d.get("added", "")},
                      **({"url": RELEASE + mirror[d["id"]]["asset"], "size": mirror[d["id"]]["size"], "current": True} if d.get("id") in mirror else {}))
                 for d in (c.get("docs") or [])],
        "status_history": history.get(c["id"], []),
    }
    dd = p.get("DEED_DATE")
    if isinstance(dd, (int, float)) and dd:
        rec["last_sale_date"] = datetime.utcfromtimestamp(dd / 1000).strftime("%Y-%m-%d")
    elif isinstance(dd, str) and dd:
        rec["last_sale_date"] = dd[:10]
    # All lots in the application (assemblages): pin at their combined center, totals across lots.
    lots = [l for l in (c.get("lots") or []) if l.get("pin")]
    if not lots and pin and p:
        lots = [{"pin": pin, "lat": p.get("lat"), "lon": p.get("lon"), "acre": p.get("CALC_ACRE"), "net": p.get("NET_VALUE")}]
    rec["parcel_pins"] = [l["pin"] for l in lots]
    if len(lots) > 1:
        pts = [(l["lat"], l["lon"]) for l in lots if l.get("lat")]
        if pts:
            rec["lat"] = round(sum(x for x, _ in pts) / len(pts), 6)
            rec["lon"] = round(sum(y for _, y in pts) / len(pts), 6)
            rec["geo_source"] = "parcel"
        by_block = defaultdict(list)
        for l in lots:
            _, blk_, lot_ = l["pin"].split("_", 2)
            by_block[blk_].append(lot_)
        def _lotkey(x):
            try:
                return float(x)
            except ValueError:
                return 1e9
        rec["lots_label"] = "; ".join(f"Block {k} · Lot{'s' if len(v) > 1 else ''} {', '.join(sorted(v, key=_lotkey))}" for k, v in by_block.items())
        rec["lots_acre"] = round(sum(float(l.get("acre") or 0) for l in lots), 3) or None
        rec["lots_net"] = sum(int(l.get("net") or 0) for l in lots) or None
    rec["product"] = product_of(c, f, kind)
    out.append(rec)
    if mail:
        by_mail[mail.upper()].add(rec["id"])

# Fill in product type where the description doesn't say what's being built:
# 1) borrow from another 2026 case on the same parcel, 2) amendments/extensions -> "changes to prior approvals",
# 3) everything else -> the parcel's tax class.
by_pin = defaultdict(list)
for r in out:
    if r["pams_pin"]:
        by_pin[r["pams_pin"]].append(r)
for r in out:
    if r["product"] != "other":
        continue
    sib = [s for s in by_pin.get(r["pams_pin"], []) if s is not r and s["product"] not in ("other", "mods", "plan", "telecom")]
    if sib:
        best = max(sib, key=lambda s: s["units"] or 0)
        r["product"] = best["product"]
        r["product_from"] = best["id"]
        if not r["units"] and best["units"]:
            r["units_ref"] = best["units"]
    elif r["kind"] in ("amend", "ext"):
        r["product"] = "mods"
    else:
        r["product"] = CLASS_PRODUCT.get(r["prop_class"] or "", "other")

# One name per attorney: "Ben Wine" and "Benjamin T.F. Wine" are the same person.
NICK = {"ben": "b", "benjamin": "b", "tom": "t", "thomas": "t", "jim": "j", "james": "j", "mike": "m", "michael": "m", "steve": "s", "stephen": "s", "steven": "s", "chuck": "c", "charles": "c"}
def person_key(name):
    first = re.split(r"\s*/\s*|\s+and\s+|,\s*", name.replace("\u2019", "'"))[0]
    toks = [t for t in re.sub(r"[^A-Za-z' -]", " ", first).split() if len(t) > 1 or t.isalpha() and False]
    if len(toks) < 2:
        return first.lower()
    f = toks[0].lower()
    return NICK.get(f, f[0]) + " " + toks[-1].lower()
groups = defaultdict(list)
for r in out:
    if r["attorney"]:
        groups[person_key(r["attorney"])].append(r)
for rs in groups.values():
    display = max((r["attorney"] for r in rs), key=lambda n: (sum(1 for x in rs if x["attorney"] == n), len(n)))
    display = re.split(r"\s*/\s*", display)[0]
    for r in rs:
        r["attorney"] = display

# When each case was approved: the first time "Approved" was seen (or the portal's completion date for the seed).
for r in out:
    r["approved_on"] = None
    if r["status_group"] == "approved":
        hit = [h for h in r["status_history"] if status_group(h[0]) == "approved"]
        r["approved_on"] = next((h[1] for h in hit if h[1]), None) or r["completed"]
    r["status_changed_on"] = r["status_history"][-1][1] if r["status_history"] and len(r["status_history"][-1]) == 2 else None

# Units counted toward the headline only once per site: new site plans that are still alive.
for r in out:
    r["counts_units"] = bool(r["kind"] == "new" and r["units"] and r["status_group"] not in ("closed", "denied"))
    r["mail_group"] = len(by_mail.get((r["owner_mail"] or "").upper(), ())) if r["owner_mail"] else 0

dest = ROOT / "data/map.json"
generated = cases_raw.get("pulled") or datetime.utcnow().isoformat() + "Z"
if dest.exists():
    try:
        old = json.loads(dest.read_text(encoding="utf-8"))
        if json.dumps(old.get("cases"), sort_keys=True) == json.dumps(out, sort_keys=True):
            generated = old.get("generated_at", generated)  # nothing changed: keep the old stamp so no commit is made
    except Exception:
        pass
data = {
    "generated_at": generated,
    "since": "2026-01-01",
    "sources": {
        "portal": "Jersey City Online Permitting & Licensing Portal (EnerGov) - plan cases P2026-*, Z2026-*",
        "agendas": "Jersey City Open Data - Planning Board Agendas 2026, Zoning Board Agendas 2026",
        "parcels": "NJOGIS Parcels Composite (MOD-IV)",
    },
    "cases": out,
}
dest.parent.mkdir(exist_ok=True)
dest.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")

# Summary for checking
from collections import Counter
print(len(out), "cases ->", dest)
print("boards", Counter(r["board"] for r in out))
print("kinds", Counter(r["kind"] for r in out))
print("products", Counter(r["product"] for r in out))
print("status", Counter(r["status_group"] for r in out))
print("located", sum(1 for r in out if r["lat"]), "applicant", sum(1 for r in out if r["applicant"]), "attorney", sum(1 for r in out if r["attorney"]))
print("units (new site plans, live)", sum(r["units"] for r in out if r["counts_units"]))

# Assemble the page: shared stylesheet from the Distress Map (src/head.html) + tracker markup/script.
(ROOT / "index.html").write_text((ROOT / "src/head.html").read_text(encoding="utf-8") + (ROOT / "src/body.html").read_text(encoding="utf-8"), encoding="utf-8")
# Standalone single file: same page with the data embedded, for opening from disk or uploading anywhere.
page = (ROOT / "index.html").read_text(encoding="utf-8")
blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
marker = '<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js"></script>'
(ROOT / "jc-board-tracker.html").write_text(page.replace(marker, f'<script id="jc-data" type="application/json">{blob}</script>\n' + marker, 1), encoding="utf-8")
# Artifact variant: claude.ai wraps the page in its own document skeleton.
stand = (ROOT / "jc-board-tracker.html").read_text(encoding="utf-8")
art = re.sub(r"^<!doctype html>\s*<html[^>]*>\s*<head>\s*", "", stand, flags=re.I)
art = re.sub(r'<meta charset="utf-8">\s*<meta name="viewport"[^>]*>\s*', "", art)
art = art.replace("</head>\n<body>", "").replace("</head>\r\n<body>", "")
art = re.sub(r"</body>\s*</html>\s*$", "", art)
(ROOT / "artifact.html").write_text(art, encoding="utf-8")
print("wrote index.html, jc-board-tracker.html, artifact.html")
