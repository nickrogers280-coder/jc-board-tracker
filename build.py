"""Build data/map.json for the JC Board Tracker from the raw pulls.

Inputs (from the browser pull):
  raw/jc_cases_2026.json    - Jersey City permit portal (EnerGov) plan cases + NJOGIS parcel match + geocode
  raw/jc_agendas_2026.json  - parsed 2026 Planning Board / Zoning Board agendas (applicant, attorney, zone, hearing dates)
"""
import json, re, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
def _raw(name, legacy):
    p = ROOT / "raw" / name
    return json.loads((p if p.exists() else ROOT / "raw" / legacy).read_text(encoding="utf-8"))
cases_raw = _raw("jc_cases.json", "jc_cases_2026.json")
agendas = _raw("jc_agendas.json", "jc_agendas_2026.json")
_mp = ROOT / "data/mirror.json"
mirror = json.loads(_mp.read_text(encoding="utf-8")) if _mp.exists() else {}
RELEASE = "https://github.com/nickrogers280-coder/jc-board-tracker/releases/download/"


def mirror_url(m):
    return RELEASE + m.get("tag", "documents") + "/" + m["asset"]
_pp = ROOT / "raw/priors.json"
priors_raw = json.loads(_pp.read_text(encoding="utf-8")) if _pp.exists() else {}
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


# ------------------------------------------------------------------ what is being proposed
# Pin categories describe the proposed project, never the lot's current use (that's shown separately).
INTERIM = r"interim use|temporary|batching plant|surface parking|valet (?:surface )?parking lot|parking lot (?:with|for|to serve)|as a parking lot"
INDUSTRIAL = r"warehouse|industrial|logistic|distribution (?:center|facility)|data center|self[- ]storage|manufactur|storage of building material|truck terminal"
COMMERCIAL = r"\bhotel|retail|restaurant|\boffices?\b|commercial|car ?wash|tire|auto(?:mobile|motive)? (?:repair|service|body)|gas station|service station|fitness|\bgym\b|school|medical|daycare|day care|church|house of worship|golf|recreation|\bstore\b|dispensar|cannabis|museum|theat(?:er|re)|supermarket|grocery|bank\b|clinic"
LARGE_RES = r"multi-?\s?family|mixed[- ]use|apartment|tower|residential (?:units|building|development|project)|dwelling units|amenit(?:y|ies)|senior housing|assisted living"
SMALL_RES = r"single[- ]family|one[- ]family|two[- ]family|1-family|2-family|townhouse|accessory dwelling|addition to (?:the |an )?existing|fourth story|third floor|on my property|my (?:home|house)"
SIGNS = r"\bsigns?\b|signage|banner|antenna|cell (?:tower|site)|telecom|wireless|supergraphic"
MINOR = r"\bsigns?\b|signage|banner|antenna|cell (?:tower|site)|telecom|wireless|awning|fa[cç]ade|solar panel|electric meter|interior (?:layout|stair|changes)"


def classify_text(desc, kind, units=None, stories=None, hotel=None):
    """Category from one description alone; None when it doesn't say what's being built."""
    d = (desc or "").lower()
    if kind == "plan":
        return "plan"
    if kind == "appeal" or re.match(r"\s*(?:request(?:ing)? (?:an? )?)?appeal", d):
        return "appeal"
    if kind == "sign":
        return "minor"
    if re.search(INTERIM, d) and not (units or 0) >= 5:
        return "interim"
    if units and units >= 5:
        return "res"
    if units and units < 5:
        return "small"
    if re.search(SIGNS, d):
        return "minor"
    if re.search(INDUSTRIAL, d):
        return "industrial"
    if re.search(SMALL_RES, d):
        return "small"
    if re.search(LARGE_RES, d) or (stories and stories >= 5 and re.search(r"residential|building", d)):
        return "res" if (stories or 5) >= 5 or re.search(r"multi-?\s?family|apartment|tower|mixed[- ]use", d) else "small"
    if re.search(r"residential", d):
        return "small"
    if hotel or re.search(COMMERCIAL, d):
        return "commercial"
    if re.search(MINOR, d):
        return "minor"
    if kind == "subdiv" or re.search(r"subdivi|consolidat|lot line", d):
        return "subdiv"
    return None


PROJECT = {"res", "small", "commercial", "industrial"}   # categories that describe a building project


def block_of(pin):
    return pin.split("_")[1] if pin and pin.count("_") >= 2 else None


def blocks_in_text(t):
    return set(re.findall(r"Block[:\s#]*(\d{3,5}(?:\.\d{1,3})?)", t or "", re.I))


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


def doc_out(d):
    o = {"name": d.get("name", ""), "note": d.get("note", ""), "added": d.get("added", "")}
    if d.get("id") in mirror:
        o.update(url=mirror_url(mirror[d["id"]]), size=mirror[d["id"]]["size"], current=True)
    elif d.get("url"):
        o.update(url=d["url"], current=True)
    return o


def build_prior(p):
    odp = p.get("odp") or {}
    text = " ".join(x for x in [p.get("desc") or "", odp.get("desc") or ""] if x)
    figs = parse_desc(text)
    grab = lambda pat: (re.search(pat, odp.get("desc") or "") or [None, ""])[1].strip(" ,")
    kind_, label_ = kind_of(p.get("type") or "") if p.get("type") else ("", "")
    docs = [doc_out(d) for d in (p.get("docs") or [])] + [doc_out(d) for d in odp.get("docs") or []]
    blocks = ({block_of(p.get("pin"))} - {None}) | blocks_in_text(text)
    return {
        "blocks": sorted(blocks),
        "id": p["id"], "case_id": p.get("caseId"), "type": p.get("type") or (odp.get("title") or "").split(" - ")[0],
        "status": p.get("status") or "", "applied": p.get("applied") or "",
        "address": re.sub(r"\s+Jersey City NJ\s*\d{5}$", "", p.get("address") or "", flags=re.I).strip() or re.sub(r"^.*?\b[PZ]\d{2,4}-\d{2,4}\s*", "", odp.get("title") or ""),
        "desc": re.sub(r"\s+", " ", p.get("desc") or "").strip() or odp.get("desc", "")[:1200],
        "applicant": grab(r"Applicant:\s*(.+?)\s+(?:Attorney|Review Planner|Block|Zone|Ward|Description):"),
        "attorney": grab(r"Attorney:\s*(.+?)\s+(?:Review Planner|Block|Zone|Ward|Description|Applicant):"),
        "odp": odp.get("dataset"), **figs, "docs": docs,
    }


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
        "tracked_because": c.get("tracked_because", "filed"),
        "approval_expires": (c.get("approvalExpires") or "")[:10] or None,
        "docs": [dict({"name": d.get("name", ""), "note": d.get("note", ""), "added": d.get("added", "")},
                      **({"url": mirror_url(mirror[d["id"]]), "size": mirror[d["id"]]["size"], "current": True} if d.get("id") in mirror else {}))
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
    rec["own_cat"] = classify_text(c.get("desc"), kind, f["units"], f["stories"], f["hotel_rooms"])
    lot_cls = [l.get("cls") for l in (c.get("lots") or []) if l.get("cls")] or ([p.get("PROP_CLASS")] if p.get("PROP_CLASS") else [])
    rec["existing"] = sorted(set(lot_cls), key=lambda x: (len(x), x))
    rec["priors"] = [build_prior(priors_raw[r]) for r in (c.get("prior_ids") or []) if r in priors_raw]
    out.append(rec)
    if mail:
        by_mail[mail.upper()].add(rec["id"])

# ------------------------------------------------------------------ resolve each case's category
# 1. This application's own description.
# 2. Extensions/amendments that don't say: the approval they extend or amend (only if it's on the same block).
# 3. Still unknown: a real building project on the same lot (never an interim use, never a borrowed type).
# 4. Otherwise: "Changes to an approved project" for amendments/extensions, "Other" for the rest.
CASE_BLOCKS = {}
for r in out:
    CASE_BLOCKS[r["id"]] = {block_of(x) for x in (r.get("parcel_pins") or [r.get("pams_pin")])} - {None}


def street_of(addr):
    a = re.sub(r"(?i)\b(jersey city|nj|new jersey|\d{5})\b", " ", addr or "").lower()
    a = re.sub(r"\b(st|street|ave|avenue|blvd|boulevard|dr|drive|pl|place|rd|road|pkwy|parkway|plz|plaza|ter|terrace|ct|court)\b\.?", " ", a)
    m = re.search(r"\d+[a-z]?(?:\s*[-&]\s*\d+[a-z]?)*\s+([a-z][a-z .']+)", a)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def matching_priors(r):
    """Earlier approvals on this case's block; with no block on record, on the same street."""
    mine = CASE_BLOCKS[r["id"]]
    good = []
    for q in r.get("priors") or []:
        if mine and q.get("blocks"):
            q["same_site"] = bool(mine & set(q["blocks"]))
        else:
            a, b_ = street_of(r.get("address")), street_of(q.get("address"))
            q["same_site"] = not a or not b_ or a == b_ or a in b_ or b_ in a
        if q["same_site"]:
            good.append(q)
    return good


def strong(r):
    """A category that stands on its own. For amendments/extensions, a passing mention of retail or a facade
    doesn't say what the project is; the approval being amended does."""
    c = r["product"]
    if c in ("res", "small", "industrial", "interim", "plan", "appeal"):
        return True
    return c == "commercial" and r["kind"] not in ("amend", "ext")


for r in out:
    r["product"], r["product_basis"] = r["own_cat"], ("this application" if r["own_cat"] else None)
    same = matching_priors(r)
    if not strong(r):
        for q in same:
            qc = classify_text(q.get("desc"), "new", q.get("units"), q.get("stories"), q.get("hotel_rooms"))
            if qc in PROJECT | {"interim"}:
                r["product"], r["product_basis"] = qc, q["id"]
                break

lenders = defaultdict(list)
for r in out:
    if r["product"] in PROJECT and (strong(r) or r["product_basis"] not in (None, "this application")) and r["kind"] in ("new", "amend", "variance", "ext"):
        for pin in r.get("parcel_pins") or [r.get("pams_pin")]:
            if pin:
                lenders[pin].append(r)
for r in out:
    if strong(r) or (r["product_basis"] and r["product_basis"] != "this application"):
        continue
    cands = [s for pin in (r.get("parcel_pins") or [r.get("pams_pin")]) if pin for s in lenders.get(pin, []) if s is not r]
    if cands and r["kind"] in ("amend", "ext", "subdiv", "new", "variance", "other"):
        best = max(cands, key=lambda s: (s["units"] or 0, s["applied"]))
        r["product"], r["product_basis"] = best["product"], best["id"]
        continue
    if not r["product"]:
        r["product"] = "minor" if r["kind"] in ("amend", "ext") else "other"
        r["product_basis"] = None

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

# Extensions and amendments that don't give a size take it from the approval they extend (same site only).
for r in out:
    src = next((q for q in r.get("priors") or [] if q.get("same_site") and (q.get("units") or q.get("stories"))), None)
    if not src or r["kind"] not in ("amend", "ext"):
        continue
    for k in ("units", "stories", "affordable", "parking", "retail_sf", "hotel_rooms"):
        if not r.get(k) and src.get(k):
            r[k] = src[k]
            r.setdefault("inherited", []).append(k)
    if r.get("inherited"):
        r["inherited_from"] = src["id"]

# ------------------------------------------------------------------ approval stage
# Where each case is in the process, from the portal status, the board agendas and the status history.
STAGES = ["filed", "review", "scheduled", "heard", "approved"]
STAGE_LABEL = {"filed": "Filed: completeness check", "review": "Under staff review", "scheduled": "Scheduled for a hearing",
               "heard": "Heard: decision / resolution pending", "approved": "Approved", "denied": "Denied", "withdrawn": "Withdrawn / void"}


def stage_of(r):
    s = (r["status"] or "").lower()
    if r["status_group"] == "approved":
        return "approved"
    if "denied" in s:
        return "denied"
    if s in ("withdrawn", "void", "closed", "expired"):
        return "withdrawn"
    if "resolution" in s:
        return "heard"
    today = datetime.now(timezone.utc).date().isoformat()
    past = [h[0] for h in r["hearings"] if h[0] and h[0] <= today]
    future = [h[0] for h in r["hearings"] if h[0] and h[0] > today]
    m = re.search(r"\bTO\s+([A-Z]+)\s+(\d{1,2}),?\s+(\d{4})", r.get("agenda_last") or "", re.I)
    if m:
        try:
            future.append(datetime.strptime(f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}", "%b %d %Y").date().isoformat())
        except ValueError:
            pass
    future = sorted(d for d in future if d > today)
    r["next_hearing"] = future[0] if future else None
    if future:
        return "scheduled"
    if past:
        return "heard"
    if s in ("submitted", "submitted - online", "incomplete", "fees due"):
        return "filed"
    return "review"


_sp = ROOT / "data/stages.json"
stage_hist = json.loads(_sp.read_text(encoding="utf-8")) if _sp.exists() else {}
_today = datetime.now(timezone.utc).date().isoformat()
for r in out:
    r["stage"] = stage_of(r)
    r["stage_label"] = STAGE_LABEL[r["stage"]]
    h = stage_hist.setdefault(r["id"], [])
    if not h or h[-1][0] != r["stage"]:
        h.append([r["stage"], _today])
    r["stage_history"] = h
_sp.write_text(json.dumps(stage_hist, indent=0, sort_keys=True), encoding="utf-8")

# ------------------------------------------------------------------ sales history
_salesp = ROOT / "raw/sales.json"
SALES = json.loads(_salesp.read_text(encoding="utf-8")) if _salesp.exists() else {}


def sales_for(pins):
    """Deeds and mortgages on these lots (county index), with prices from the state sales file matched by book/page."""
    seen, outl = set(), []
    for pin in pins:
        rec = SALES.get(pin) or {}
        sr = {(s.get("book"), s.get("page")): s for s in rec.get("sr1a") or []}
        used = set()
        for d in rec.get("deeds") or []:
            key = d.get("instrument") or (d.get("recorded"), d.get("bookpage"), d.get("type"))
            if key in seen:
                continue
            seen.add(key)
            bk, _, pg = (d.get("bookpage") or "").partition("/")
            s = sr.get((bk.lstrip("0"), pg.lstrip("0"))) if "deed" in d["type"].lower() else None
            if s:
                used.add((s.get("book"), s.get("page")))
            outl.append({"date": d.get("recorded"), "type": d["type"], "from": d.get("from"), "to": d.get("to"), "bookpage": d.get("bookpage"),
                         "price": s.get("price") if s else None, "usable": s.get("usable") if s else None, "nu": s.get("nu") if s else None,
                         "n_lots": s.get("n_lots") if s else None, "pin": pin})
        for k, s in sr.items():
            if k in used or ("sr1a",) + k in seen:
                continue
            seen.add(("sr1a",) + k)
            outl.append({"date": s.get("recorded") or s.get("deed_date"), "type": "Deed (state sales record)", "from": None, "to": None,
                         "bookpage": f"{k[0]}/{k[1]}", "price": s.get("price"), "usable": s.get("usable"), "nu": s.get("nu"), "n_lots": s.get("n_lots"), "pin": pin})
    outl.sort(key=lambda x: x.get("date") or "", reverse=True)
    return outl[:80]


GOV = re.compile(r"DEPARTMENT OF ENV|\bNJDEP\b|DEPARTMENT OF PROTECTION|CITY OF\b|COUNTY OF\b|REDEVELOPMENT AGENCY|STATE OF NEW JERSEY", re.I)
ORG = re.compile(r"\b(LLC|L\.L\.C|INC|LP|L\.P|CORP|COMPANY|CO|ASSOC|ASSOCIATION|TRUST|AUTHORITY|UNIVERSITY|CONDOMINIUM|PARTNERS|HOLDINGS|BANK|FUND)\b", re.I)


def owner_from_deeds(pins):
    """Owner of record from the newest deed on the lot (county index): the grantee, or the grantor when the grantee
    is a government body (DEP deed notices, easements to the City). A unit sale to a person marks a condominium."""
    deeds = []
    for pin in pins or []:
        deeds += [d for d in (SALES.get(pin) or {}).get("deeds") or [] if re.match(r"deed", d.get("type") or "", re.I) and "master" not in (d.get("type") or "").lower()]
    if not deeds:
        return None
    d = max(deeds, key=lambda x: x.get("recorded") or "")
    to, frm = (d.get("to") or "").strip(), (d.get("from") or "").strip()
    owner, note = (frm, "government party on the deed") if GOV.search(to) else (to, "")
    if owner and not ORG.search(owner):
        owner, note = (f"Condominium; sponsor {frm.title()}" if ORG.search(frm) else "Condominium (individually owned units)"), "latest deed is a unit sale"
    return {"owner": owner.title() if owner.isupper() else owner, "date": d.get("recorded"), "bookpage": d.get("bookpage"), "note": note} if owner else None


for r in out:
    r["sales"] = sales_for(r.get("parcel_pins") or [r.get("pams_pin")])
    r["sales_checked"] = bool(any(p in SALES for p in (r.get("parcel_pins") or [r.get("pams_pin")]) if p))

# Units counted toward the headline only once per site: new site plans that are still alive.
for r in out:
    r["counts_units"] = bool(r["kind"] == "new" and r["units"] and r["status_group"] not in ("closed", "denied"))
    r["mail_group"] = len(by_mail.get((r["owner_mail"] or "").upper(), ())) if r["owner_mail"] else 0

# Split: the map loads a light summary of every case; documents, earlier approvals and sales load per case when it's
# opened, from data/detail/<shard>.json (64 shards keyed by case number).
N_SHARDS = 64


def shard_of(case_id):
    return sum(map(ord, case_id)) % N_SHARDS


shards = defaultdict(dict)
full = [dict(r) for r in out]  # keeps everything, for the single-file version
for r in out:
    shards[shard_of(r["id"])][r["id"]] = {"docs": r.pop("docs", []), "priors": r.get("priors") or [], "sales": r.pop("sales", [])}
    d = shards[shard_of(r["id"])][r["id"]]
    r["n_docs"], r["n_cur_docs"], r["n_sales"] = len(d["docs"]), sum(1 for x in d["docs"] if x.get("current")), len(d["sales"])
    r["n_transfers"] = sum(1 for x in d["sales"] if "deed" in (x.get("type") or "").lower() and "mortgage" not in (x.get("type") or "").lower())
    r["priors"] = [{"id": q.get("id"), "applicant": q.get("applicant")} for q in d["priors"]]
    r["shard"] = shard_of(r["id"])
ddir = ROOT / "data/detail"
ddir.mkdir(parents=True, exist_ok=True)
for f in ddir.glob("*.json"):
    if int(f.stem) not in shards:
        f.unlink()
for k, v in shards.items():
    blob_ = json.dumps(v, separators=(",", ":"), sort_keys=True)
    f = ddir / f"{k}.json"
    if not f.exists() or f.read_text(encoding="utf-8") != blob_:
        f.write_text(blob_, encoding="utf-8")

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
    "since": "2018-01-01",
    "sources": {
        "portal": "Jersey City Online Permitting & Licensing Portal (EnerGov) - plan cases filed 2018 on (P18-* to P22-*, P2023-* on; Z likewise)",
        "agendas": "Jersey City Open Data - Planning Board and Zoning Board agendas, 2016 on",
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

# ------------------------------------------------------------------ Kushner / KRE portfolio page data
_pf = ROOT / "raw/portfolio.json"
if _pf.exists():
    tracked = {r["id"]: r for r in out}
    pf_cfg = json.loads((ROOT / "portfolio.json").read_text(encoding="utf-8"))
    buildings = []
    for bld in json.loads(_pf.read_text(encoding="utf-8")):
        cases = []
        for c in bld.get("cases") or []:
            odp = c.get("odp") or {}
            figs = parse_desc(c.get("desc") or "")
            k, kl = kind_of(c.get("type") or "") if c.get("type") else ("other", "Archived application")
            live = tracked.get(c["id"])
            cases.append({
                "id": c["id"], "case_id": c.get("caseId"), "type": c.get("type") or "", "kind": k, "kind_label": kl,
                "status": c.get("status") or "", "applied": c.get("applied") or "", "address": c.get("address") or "",
                "desc": c.get("desc") or "", "odp": odp.get("dataset"), **{x: figs[x] for x in ("units", "stories")},
                "stage": live["stage"] if live else None, "stage_label": live["stage_label"] if live else None,
                "next_hearing": live.get("next_hearing") if live else None,
                "docs": [doc_out(d) for d in c.get("docs") or []] + [doc_out(d) for d in odp.get("docs") or []],
            })
        def ckey(c):
            m = re.match(r"[PZ](\d{2,4})-(\d+)", c["id"])
            y = int(m.group(1)) if m else 0
            y = y + 2000 if y < 100 else y
            return (c["applied"] or f"{y}-00-00", int(m.group(2)) if m else 0)
        cases.sort(key=ckey, reverse=True)
        lots = bld.get("lots") or []
        pins = bld.get("pins") or []
        by_block = defaultdict(list)
        for p_ in pins:
            _, bk, lt = p_.split("_", 2)
            by_block[bk].append(lt)
        buildings.append({
            "id": bld["id"], "name": bld["name"], "company": bld["company"], "partners": bld.get("partners") or [],
            "developers": bld.get("developers") or [{"key": bld["company"], "role": "Developer"}],
            "owner_mail": bld.get("owner_mail") or next((", ".join(x for x in [(l.get("ST_ADDRESS") or "").strip(), (l.get("CITY_STATE") or "").strip()] if x) for l in (bld.get("lots") or []) if l.get("ST_ADDRESS")), None),
            "discovered": bool(bld.get("discovered")),
            "owner_of_record": bld.get("owner_of_record") or owner_from_deeds(pins),
            "status": bld.get("status"), "completed": bld.get("completed"), "units": bld.get("units"), "stories": bld.get("stories"),
            "summary": bld.get("summary"), "sources": bld.get("sources") or [], "addresses": bld.get("addresses") or [],
            "lat": bld.get("lat") or (lots[0].get("lat") if lots else None), "lon": bld.get("lon") or (lots[0].get("lon") if lots else None),
            "pins": pins, "lots_label": "; ".join(f"Block {k} · Lot{'s' if len(v) > 1 else ''} {', '.join(v)}" for k, v in by_block.items()),
            "existing": sorted({l.get("PROP_CLASS") for l in lots if l.get("PROP_CLASS")}),
            "net_value": sum(int(l.get("NET_VALUE") or 0) for l in lots) or None, "acres": round(sum(float(l.get("CALC_ACRE") or 0) for l in lots), 3) or None,
            "cases": cases, "sales": sales_for(pins),
        })
    port = {"generated_at": generated, "title": pf_cfg.get("title"), "note": pf_cfg.get("note"), "developers": pf_cfg.get("developers") or [], "buildings": buildings}
    (ROOT / "data/portfolio.json").write_text(json.dumps(port, separators=(",", ":")), encoding="utf-8")
    print(f"portfolio: {len(buildings)} buildings, {sum(len(x['cases']) for x in buildings)} cases, {sum(len(c['docs']) for x in buildings for c in x['cases'])} documents")

# Assemble the page: shared stylesheet from the Distress Map (src/head.html) + tracker markup/script.
(ROOT / "index.html").write_text((ROOT / "src/head.html").read_text(encoding="utf-8") + (ROOT / "src/body.html").read_text(encoding="utf-8"), encoding="utf-8")
if (ROOT / "src/portfolio.html").exists():
    _dev = (ROOT / "src/head.html").read_text(encoding="utf-8").replace("<title>JC Board Tracker</title>", "<title>Jersey City Developers</title>") + (ROOT / "src/portfolio.html").read_text(encoding="utf-8")
    for _n in ("developers.html", "kushner.html"):  # kushner.html kept so links already sent keep working
        (ROOT / _n).write_text(_dev, encoding="utf-8")
# Standalone single file: same page with the data embedded, for opening from disk or uploading anywhere.
page = (ROOT / "index.html").read_text(encoding="utf-8")
blob = json.dumps({**data, "cases": full}, separators=(",", ":")).replace("</", "<\\/")
marker = '<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js"></script>'
_bp = ROOT / "data/boundaries.json"
bblob = (f'<script id="jc-bounds" type="application/json">{_bp.read_text(encoding="utf-8").replace("</", "<\\/")}</script>\n') if _bp.exists() else ""
(ROOT / "jc-board-tracker.html").write_text(page.replace(marker, f'<script id="jc-data" type="application/json">{blob}</script>\n' + bblob + marker, 1), encoding="utf-8")
# Artifact variant: claude.ai wraps the page in its own document skeleton.
stand = (ROOT / "jc-board-tracker.html").read_text(encoding="utf-8")
art = re.sub(r"^<!doctype html>\s*<html[^>]*>\s*<head>\s*", "", stand, flags=re.I)
art = re.sub(r'<meta charset="utf-8">\s*<meta name="viewport"[^>]*>\s*', "", art)
art = art.replace("</head>\n<body>", "").replace("</head>\r\n<body>", "")
art = re.sub(r"</body>\s*</html>\s*$", "", art)
(ROOT / "artifact.html").write_text(art, encoding="utf-8")
print("wrote index.html, jc-board-tracker.html, artifact.html")
