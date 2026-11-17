"""Pull the latest Jersey City Planning/Zoning Board cases, agendas and documents.

Writes raw/jc_cases.json and raw/jc_agendas.json for build.py, and keeps data/history.json
(each case's status changes, with the date each new status was first seen).

Sources (all public, no sign-in):
  - Jersey City Online Permitting & Licensing Portal (Tyler EnerGov self-service API)
  - Jersey City Open Data: Planning Board / Zoning Board agenda PDFs
  - NJOGIS Parcels Composite (MOD-IV) for parcel location and tax record
  - Esri World Geocoder for cases whose parcel number doesn't match the tax map
"""
import io
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).parent
FIRST_YEAR = 2018
TODAY = date.today()
YEARS = list(range(FIRST_YEAR, TODAY.year + 1))
REFRESH_CLOSED_DAYS = 14  # closed cases are re-read from the portal every two weeks; open ones every run


def case_prefixes(year):
    """Portal case numbers: P18-102 / Z19-045 through 2022 (legacy), P2023-0001 / Z2023-0001 after. Both are tried around the switch."""
    out = []
    for b in ("P", "Z"):
        if year <= 2023:
            out.append(f"{b}{year % 100:02d}-")
        if year >= 2022:
            out.append(f"{b}{year}-")
    return out


# Agenda datasets on JC Open Data have a different name almost every year. Several per year are fine: dates are de-duplicated.
AGENDA_SETS = {
    2016: [("zoning-board-of-adjustment-action-agendas-2016-pdf", "Z")],
    2020: [("planning-board-agendas-2020", "P"), ("planning-board-action-agendas-2020", "P"), ("zoning-board-action-agendas-2020", "Z")],
    2021: [("planning-board-agendas-2021", "P"), ("pb-action-agendas-2021", "P"), ("zoning-board-agendas-2021", "Z"),
           ("zoning-board-of-adjustment-action-agendas-2021", "Z")],
    2022: [("planning-board-agendas-2022", "P"), ("pb-action-agendas-2022", "P"), ("zoning-board-agendas-2022", "Z"), ("zoning-board-action-agendas-2022", "Z")],
    2023: [("pb-agendas-2023", "P"), ("pb-action-agendas-2023", "P"), ("zba-agendas-2023", "Z"), ("zoning-board-agenda-2023", "Z")],
    2024: [("planning-board-2024-agendas", "P"), ("planning-board-agendas-from-2024", "P"), ("zba-agendas-2024", "Z")],
}


def agenda_sets(year):
    return AGENDA_SETS.get(year) or [(f"planning-board-agendas-{year}", "P"), (f"zb-agendas-{year}", "Z")]

API = "https://jerseycitynj-energovpub.tylerhost.net/apps/selfservice/api/energov/"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
    "tenantId": "1",
    "tenantName": "JerseyCityNJProd",
    "Tyler-TenantUrl": "JerseyCityNJProd",
    "Tyler-Tenant-Culture": "en-US",
    "User-Agent": "Mozilla/5.0 (JC Board Tracker; +https://nickrogers280-coder.github.io/jc-board-tracker/)",
    "Referer": "https://jerseycitynj-energovpub.tylerhost.net/apps/selfservice/JerseyCityNJProd",
}
PARCELS = "https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/Parcels_Composite_NJ_WM/FeatureServer/0/query"
GEOCODE = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
ODP = "https://data.jerseycitynj.gov/api/datasets/1.0/"

s = requests.Session()
s.headers.update(HEADERS)


def get(url, **kw):
    for attempt in range(4):
        try:
            r = s.get(url, timeout=60, **kw)
            if r.status_code < 500:
                return r
        except requests.RequestException:
            pass
        time.sleep(2 + attempt * 3)
    raise RuntimeError(f"GET failed: {url}")


def post(url, **kw):
    for attempt in range(4):
        try:
            r = s.post(url, timeout=60, **kw)
            if r.status_code < 500:
                return r
        except requests.RequestException:
            pass
        time.sleep(2 + attempt * 3)
    raise RuntimeError(f"POST failed: {url}")


# ------------------------------------------------------------------ cases
def search_cases(prefix):
    crit = get(API + "search/criteria").json()["Result"]
    out, page, pages = [], 1, 1
    while page <= pages:
        b = json.loads(json.dumps(crit))
        b.update(Keyword=prefix, SearchModule=1, FilterModule=3, PageNumber=page, PageSize=100, SortBy="PlanNumber.keyword", SortAscending=True)
        b["PlanCriteria"].update(PlanTypeId="none", PlanStatusId="none", SortBy="PlanNumber.keyword")
        j = post(API + "search/search", json=b).json()
        res = j.get("Result") or {}
        pages = res.get("TotalPages") or 1
        out += [x for x in (res.get("EntityResults") or []) if (x.get("CaseNumber") or "").startswith(prefix)]
        page += 1
    return out


def plan_detail(case_id):
    j = get(API + f"plans/{case_id}").json()
    return j.get("Result") or {}


def location_pins(case_id):
    """Every parcel the portal lists on the case's Locations tab."""
    body = {"PageNumber": 1, "PageSize": 100, "SortField": None, "IsSortedInAscendingOrder": True, "ModuleId": 2, "EntityId": case_id}
    j = post(API + "address/locationData", json=body).json()
    pins = []
    for x in j.get("Result") or []:
        for k in ("Parcel", "Address"):
            pn = (x.get(k) or {}).get("ParcelNumber")
            if pn and pn not in pins:
                pins.append(pn)
    return pins


LOT = r"\d{1,4}(?:\.\d{1,3})?"
LOTS = rf"{LOT}(?:\s*(?:,|&|and|,\s*and)\s*{LOT})*"
BLOCK = r"\d{3,5}(?:\.\d{1,3})?"


def text_pins(text, main_pin):
    """Lots named in a description or agenda: 'Block 18202, Lots 11, 12, 13, and 14', 'Lots 62, 63 and 64 Block 19301', 'lots 35 and 36'."""
    if not text:
        return []
    t = re.sub(r"\s+", " ", text)
    main_block = main_pin.split("_")[1] if main_pin and main_pin.count("_") >= 2 else None
    found = []
    def add(block, lots):
        for lot in re.findall(LOT, lots):
            pin = f"0906_{block}_{lot}"
            if pin not in found:
                found.append(pin)
    for m in re.finditer(rf"Block[:\s]*({BLOCK})[,;\s]*(?:and\s+)?Lots?[:\s]*({LOTS})(?![\d-])", t, re.I):
        add(m.group(1), m.group(2))
    for m in re.finditer(rf"Lots?[:\s]*({LOTS})[,\s]*(?:on|in|of)?\s*Block[:\s]*({BLOCK})", t, re.I):
        add(m.group(2), m.group(1))
    if main_block and not found:
        for m in re.finditer(rf"\blots\s+({LOTS})", t, re.I):
            add(main_block, m.group(1))
    return found


def attachments(case_id):
    j = get(API + f"entity/attachments/search/entityattachments/{case_id}/2/true").json()
    res = j.get("Result") or {}
    docs = []
    for a in res.get("Attachments") or []:
        docs.append({
            "name": a.get("FileName") or "",
            "note": (a.get("Notes") or "").strip(),
            "added": (a.get("AddedOn") or "")[:10],
            "id": a.get("AttachmentID"),
        })
    docs.sort(key=lambda d: d["added"], reverse=True)
    return docs


# ------------------------------------------------------------------ earlier approvals (extensions / amendments)
REF = re.compile(r"(?<![A-Za-z0-9])(?:Case\s*(?:No\.?|Number|#)?\s*)?([PZ])?\s?-?\s?(20\d{2}|\d{2})\s?-\s?(\d{2,4})(?![\d-])", re.I)


def prior_refs(text, own_id):
    """Case numbers an application cites: 'P21-013', 'P2024-0187', 'Case No. 22-057', 'Z20-102'."""
    refs = []
    for m in REF.finditer(text or ""):
        letter, yr, num = (m.group(1) or "").upper(), m.group(2), m.group(3)
        ctx = text[max(0, m.start() - 12):m.start()].lower()
        if not letter and "case" not in (text[max(0, m.start() - 12):m.end()].lower()):
            continue  # bare "22-057" only counts when it's called a case
        letter = letter or own_id[0]
        if len(yr) == 4:
            if not 2000 <= int(yr) <= TODAY.year:
                continue
            ref = f"{letter}{yr}-{int(num):04d}"
        else:
            if int(yr) > TODAY.year % 100:
                continue
            ref = f"{letter}{yr}-{int(num):03d}"
        if ref != own_id and ref not in refs and "res" not in ctx:
            refs.append(ref)
    return refs


_CRIT = None


def find_case(ref):
    global _CRIT
    _CRIT = _CRIT or get(API + "search/criteria").json()["Result"]
    b = json.loads(json.dumps(_CRIT))
    b.update(Keyword=ref, ExactMatch=True, SearchModule=1, FilterModule=3, PageNumber=1, PageSize=20, SortBy="PlanNumber.keyword", SortAscending=True)
    b["PlanCriteria"].update(PlanTypeId="none", PlanStatusId="none", SortBy="PlanNumber.keyword")
    res = (post(API + "search/search", json=b).json().get("Result") or {}).get("EntityResults") or []
    return next((x for x in res if (x.get("CaseNumber") or "").upper() == ref.upper()), None)


def odp_case(ref):
    """Pre-portal applications are archived on Jersey City Open Data, one dataset per case, with plans attached."""
    q = requests.get("https://data.jerseycitynj.gov/api/explore/v2.1/catalog/datasets",
                     params={"where": f'search("{ref.lower()}")', "limit": 10, "select": "dataset_id,title"}, timeout=60)
    tok = ref.lower()
    hit = next((d for d in q.json().get("results", []) if re.search(rf"(?<![a-z0-9]){re.escape(tok)}(?![0-9])", d["dataset_id"])), None)
    if not hit:
        return None
    meta = get(ODP + hit["dataset_id"] + "/").json()
    desc = re.sub(r"<[^>]+>", " ", str((meta.get("metas") or {}).get("description") or ""))
    desc = re.sub(r"\s+", " ", desc).strip()
    docs = [{"name": a.get("title") or a.get("id"), "url": ODP + f"{hit['dataset_id']}/attachments/{a['id']}/"} for a in meta.get("attachments") or []]
    return {"dataset": hit["dataset_id"], "title": hit["title"], "desc": desc, "docs": docs}


def load_prior(ref, cache):
    c = cache.get(ref)
    if c and c.get("checked", "") >= (TODAY.fromordinal(TODAY.toordinal() - 14)).isoformat():
        return c
    rec = {"id": ref, "checked": TODAY.isoformat()}
    x = find_case(ref)
    if x:
        d = plan_detail(x["CaseId"])
        rec.update(caseId=x["CaseId"], type=x.get("CaseType"), status=x.get("CaseStatus"), applied=(x.get("ApplyDate") or "")[:10],
                   address=x.get("AddressDisplay"), desc=d.get("Description") or x.get("Description") or "", pin=d.get("MainParcelNumber"))
        try:
            rec["docs"] = attachments(x["CaseId"])
        except Exception:
            rec["docs"] = (c or {}).get("docs", [])
    try:
        o = odp_case(ref)
    except Exception:
        o = (c or {}).get("odp")
    if o:
        rec["odp"] = o
    if not x and not o:
        rec["missing"] = True
    cache[ref] = rec
    return rec


# ------------------------------------------------------------------ parcels / geocode
PFIELDS = "PAMS_PIN,PCLBLOCK,PCLLOT,PROP_CLASS,PROP_LOC,OWNER_NAME,ST_ADDRESS,CITY_STATE,ZIP_CODE,LAND_VAL,IMPRVT_VAL,NET_VALUE,CALC_ACRE,BLDG_DESC,LAND_DESC,DEED_DATE,SALE_PRICE,YR_CONSTR,ADD_LOTS1"


def parcels(pins):
    found = {}
    pins = sorted(set(p for p in pins if p))
    for i in range(0, len(pins), 40):
        chunk = pins[i:i + 40]
        where = "PAMS_PIN IN (" + ",".join("'" + p.replace("'", "''") + "'" for p in chunk) + ")"
        r = requests.post(PARCELS, data={"where": where, "outFields": PFIELDS, "returnGeometry": "false", "returnCentroid": "true", "outSR": "4326", "f": "json"}, timeout=90)
        for f in r.json().get("features", []):
            a = f["attributes"]
            c = f.get("centroid") or {}
            a["lat"], a["lon"] = c.get("y"), c.get("x")
            found[a["PAMS_PIN"]] = a
    return found


def geocode(address):
    a = re.sub(r"Unit:.*?(?=Jersey City)", "", address or "").strip()
    if not a or not re.search(r"\d", a):
        return None
    if "jersey city" not in a.lower():
        a += ", Jersey City, NJ"
    r = requests.get(GEOCODE, params={"SingleLine": a, "f": "json", "maxLocations": 1, "outFields": "Score,Addr_type"}, timeout=60)
    c = (r.json().get("candidates") or [None])[0]
    if not c:
        return None
    return {"lat": c["location"]["y"], "lon": c["location"]["x"], "score": c["score"], "t": c["attributes"].get("Addr_type"), "m": c.get("address")}


# ------------------------------------------------------------------ agendas
MONTHS = {m: i for i, m in enumerate("january february march april may june july august september october november december".split(), 1)}
MONTHS.update(jun=6, jul=7, aug=8, sept=9, oct=10)


def agenda_date(att_id, year):
    m = re.search(r"(january|february|march|april|may|june|jun|july|jul|august|aug|september|sept|october|oct|november|december)_(\d{1,2})", att_id, re.I)
    if not m:
        return None
    return f"{year}-{MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"


def agenda_text(url):
    import pdfplumber
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def parse_agendas(seen_cache):
    """Return {case: {dates, app, att, zone, bl, last}} across every agenda for the tracked years."""
    ag, agenda_ids = {}, []
    for year in YEARS:
        for ds, board in agenda_sets(year):
            r = get(ODP + ds + "/")
            if r.status_code != 200:
                continue
            for att in r.json().get("attachments", []):
                aid = att["id"]
                if re.search(r"cancel", aid, re.I):
                    continue
                agenda_ids.append(f"{ds}/{aid}")
                key = f"{ds}/{aid}"
                text = seen_cache.get(key)
                if text is None:
                    try:
                        text = agenda_text(ODP + f"{ds}/attachments/{aid}/")
                    except Exception as e:  # one bad PDF shouldn't stop the update
                        print("agenda failed", key, e, file=sys.stderr)
                        continue
                    seen_cache[key] = text
                d = agenda_date(aid, year) or ""
                t = re.sub(r"https?://\S+", "", text)
                t = re.sub(r"\s+-\s+", "-", t)
                for part in re.split(r"C\s?ase\s?:\s*", t)[1:]:
                    m = re.match(r"([PZ])\s?(\d{4}|\d{2})\s?-\s?(\d{2,4})(?!\d)", part)
                    if not m:
                        continue
                    cn = (f"{m.group(1)}{m.group(2)}-{int(m.group(3)):04d}" if len(m.group(2)) == 4
                          else f"{m.group(1)}{m.group(2)}-{int(m.group(3)):03d}")
                    rec = ag.setdefault(cn, {"dates": []})
                    rec["dates"].append(d + board)

                    def g(pat):
                        x = re.search(pat, part)
                        return re.sub(r"\s+", " ", x.group(1)).strip() if x else ""

                    for k, pat in (("app", r"Applicant\s*:\s*([^\n]+)"), ("att", r"Attorney\s*:\s*([^\n]+)"), ("zone", r"Zon(?:e|ing)\s*:\s*([^\n]+)"), ("bl", r"Block\s*:?\s*([^\n]+)")):
                        v = g(pat)
                        if v:
                            rec[k] = v
                    st = re.search(r"(ADJOURNED[^\n]*|CARRIED[^\n]*|WITHDRAWN[^\n]*|APPROVED[^\n]*|DENIED[^\n]*)", part)
                    if st:
                        rec["last"] = st.group(1).strip()
    for rec in ag.values():
        rec["dates"] = sorted(set(rec["dates"]))
    return ag, agenda_ids


# Statuses that mean a case is decided or dead; an older case with any other status is still in play.
CLOSED = {"approved", "complete", "denied", "withdrawn", "void", "closed", "expired", "approved, conditions pending"}


# ------------------------------------------------------------------ main
CITY_GIS = "https://services2.arcgis.com/UXbywc7dSkfgdPp4/arcgis/rest/services/"


def refresh_boundaries():
    """City limits and ward lines from Jersey City Planning's own zoning-map layers. Refreshed monthly."""
    path = ROOT / "data/boundaries.json"
    if path.exists():
        try:
            old = json.loads(path.read_text())
            if old.get("pulled", "") >= TODAY.fromordinal(TODAY.toordinal() - 30).isoformat():
                return
        except Exception:
            pass

    def layer(name):
        r = requests.get(CITY_GIS + f"{name}/FeatureServer/0/query", params={"where": "1=1", "outFields": "*", "returnGeometry": "true",
                         "outSR": "4326", "geometryPrecision": "6", "f": "geojson"}, timeout=120)
        r.raise_for_status()
        return r.json()["features"]

    try:
        city, wards = layer("Municipal_Boundary"), layer("Wards")
    except Exception as e:
        print("boundary refresh failed; keeping the last copy:", e, file=sys.stderr)
        return
    if not city or len(wards) < 6:
        print("boundary refresh returned too little; keeping the last copy", file=sys.stderr)
        return
    out = {
        "source": "Jersey City Division of City Planning, Interactive Zoning Map (Municipal Boundary, Wards)",
        "pulled": TODAY.isoformat(),
        "city": {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"name": "Jersey City"}, "geometry": f["geometry"]} for f in city]},
        "wards": {"type": "FeatureCollection", "features": sorted(
            [{"type": "Feature", "properties": {"ward": re.sub(r"(?i)^ward\s*", "", str(f["properties"].get("NAME") or "")).strip()}, "geometry": f["geometry"]} for f in wards],
            key=lambda f: f["properties"]["ward"])},
    }
    path.write_text(json.dumps(out, separators=(",", ":")))
    print("boundaries refreshed")


def main():
    (ROOT / "raw").mkdir(exist_ok=True)
    (ROOT / "data").mkdir(exist_ok=True)
    refresh_boundaries()
    (ROOT / "data").mkdir(exist_ok=True)
    cache_path = ROOT / "raw/agenda_text_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    prev = {}
    prev_path = ROOT / "raw/jc_cases.json"
    if prev_path.exists():
        prev = {c["id"]: c for c in json.loads(prev_path.read_text())["cases"]}

    # Agendas first: they decide which older cases are still in play.
    ag, agenda_ids = parse_agendas(cache)
    cache_path.write_text(json.dumps(cache))

    # Cases: everything filed since Jan 1 of FIRST_YEAR; older filings still under review; any case on a
    # tracked-year board agenda; and anything tracked before (so an older case stays when it gets approved).
    rows, why = [], {}
    for y in YEARS:
        for pre in case_prefixes(y):
            for x in search_cases(pre):
                if x["CaseNumber"] not in why:
                    rows.append(x)
                    why[x["CaseNumber"]] = "filed"
    print(f"{len(rows)} cases filed since {FIRST_YEAR}")
    if len(rows) < 500:
        sys.exit("Portal returned too few cases; leaving the published data alone.")
    extra = [c for c in list(ag) + list(prev) if c not in why]
    for ref in sorted(set(extra)):
        try:
            x = find_case(ref)
        except Exception:
            x = None
        if x:
            rows.append(x)
            why[x["CaseNumber"]] = "agenda" if ref in ag else "tracked"
    print(f"{len(rows)} cases tracked ({sum(1 for v in why.values() if v != 'filed')} filed before {FIRST_YEAR})")

    cases = []
    fresh_after = TODAY.fromordinal(TODAY.toordinal() - REFRESH_CLOSED_DAYS).isoformat()
    reused = 0
    for i, x in enumerate(rows):
        cid = x["CaseId"]
        old = prev.get(x["CaseNumber"])
        closed = (x.get("CaseStatus") or "").strip().lower() in CLOSED
        if old and closed and old.get("status") == x.get("CaseStatus") and old.get("checked", "") >= fresh_after:
            cases.append({**old, "tracked_because": why.get(x["CaseNumber"], "filed")})
            reused += 1
            continue
        try:
            d = plan_detail(cid)
        except Exception as e:
            print("detail failed", x["CaseNumber"], e, file=sys.stderr)
            d = {}
        try:
            loc = location_pins(cid)
        except Exception:
            loc = (prev.get(x["CaseNumber"]) or {}).get("loc_pins", [])
        try:
            docs = attachments(cid)
        except Exception as e:
            print("attachments failed", x["CaseNumber"], e, file=sys.stderr)
            docs = (prev.get(x["CaseNumber"]) or {}).get("docs", [])
        cases.append({
            "id": x["CaseNumber"], "caseId": cid, "type": x.get("CaseType"), "workclass": x.get("CaseWorkclass"),
            "status": x.get("CaseStatus"), "applied": x.get("ApplyDate"), "expires": x.get("ExpireDate"),
            "completed": x.get("CompleteDate"), "ward": d.get("DistrictName"), "planner": d.get("AssignedTo"),
            "address": x.get("AddressDisplay"), "project": d.get("ProjectName"),
            "pin": d.get("MainParcelNumber") or x.get("MainParcel"), "desc": d.get("Description") or x.get("Description"),
            "approvalExpires": d.get("ApprovalExpireDate"), "docs": docs, "loc_pins": loc,
            "tracked_because": why.get(x["CaseNumber"], "filed"), "checked": TODAY.isoformat(),
        })
        if i % 25 == 0:
            print(f"  details {i}/{len(rows)}")
    print(f"  {reused} closed cases reused from the last run")

    # Parcels: only look up pins we haven't matched before (tax data changes yearly, not daily).
    pins = [c["pin"] for c in cases if c["pin"]]
    known = {c["pin"]: c.get("parcel") for c in prev.values() if c.get("parcel")}
    fresh = parcels([p for p in pins if p not in known])
    for c in cases:
        c["parcel"] = known.get(c["pin"]) or fresh.get(c["pin"])
        old = prev.get(c["id"]) or {}
        if c["parcel"]:
            c["geo"] = None
        elif old.get("geo") and old.get("address") == c["address"]:
            c["geo"] = old["geo"]
        else:
            try:
                c["geo"] = geocode(c["address"])
            except Exception:
                c["geo"] = None

    # Every lot in each application: portal locations + lots named in the description/agenda + the tax
    # record's "additional lots". Only lots that exist on the state parcel map are kept.
    lot_cache = {}
    for c in cases:
        main = c["pin"] or ""
        cand = [main] + (c.get("loc_pins") or [])
        cand += text_pins(c.get("desc"), main) + text_pins((ag.get(c["id"]) or {}).get("bl", "") and "Block " + ag[c["id"]]["bl"], main)
        add = ((c.get("parcel") or {}).get("ADD_LOTS1") or "").strip()
        if add and main.count("_") >= 2:
            cand += [f"0906_{main.split('_')[1]}_{l}" for l in re.findall(LOT, add)]
        c["cand_pins"] = [p for i, p in enumerate(cand) if p and p not in cand[:i]]
    need = {p for c in cases for p in c["cand_pins"]} - set(known) - set(fresh)
    more = parcels(sorted(need)) if need else {}
    allp = {**known, **fresh, **more}
    for c in cases:
        c["lots"] = [{"pin": p, "lat": allp[p].get("lat"), "lon": allp[p].get("lon"), "acre": allp[p].get("CALC_ACRE"),
                      "net": allp[p].get("NET_VALUE"), "cls": allp[p].get("PROP_CLASS"), "loc": allp[p].get("PROP_LOC")}
                     for p in c["cand_pins"] if p in allp]

    # Earlier approvals each case builds on (extensions, amendments, re-filings), followed up to two steps back.
    pcache_path = ROOT / "raw/prior_cache.json"
    pcache = json.loads(pcache_path.read_text()) if pcache_path.exists() else {}
    own = {c["id"] for c in cases}
    for c in cases:
        chain, queue, seen = [], prior_refs(c.get("desc"), c["id"]), set()
        depth = 0
        while queue and depth < 2 and len(chain) < 4:
            nxt = []
            for ref in queue:
                if ref in seen or ref in own:
                    continue
                seen.add(ref)
                try:
                    p = load_prior(ref, pcache)
                except Exception as e:
                    print("prior lookup failed", ref, e, file=sys.stderr)
                    continue
                if p.get("missing"):
                    continue
                chain.append(ref)
                nxt += prior_refs((p.get("desc") or "") + " " + ((p.get("odp") or {}).get("desc") or ""), ref)
            queue, depth = nxt, depth + 1
        c["prior_ids"] = chain
    pcache_path.write_text(json.dumps(pcache))
    used = {r for c in cases for r in c["prior_ids"]}
    (ROOT / "raw/priors.json").write_text(json.dumps({r: pcache[r] for r in used if r in pcache}))
    print(f"earlier approvals linked: {len(used)} cases across {sum(1 for c in cases if c['prior_ids'])} applications")

    # Status history: the date each status was first seen. Seeds from the portal's completion date.
    hist_path = ROOT / "data/history.json"
    hist = json.loads(hist_path.read_text()) if hist_path.exists() else {}
    stamp = TODAY.isoformat()
    for c in cases:
        h = hist.setdefault(c["id"], [])
        if not h:
            first = (c.get("completed") or "")[:10] if (c["status"] or "").lower() in ("approved", "complete", "denied", "withdrawn", "void") else ""
            h.append([c["status"], first, "seed"])  # seed: date unknown unless the portal has a completion date
        elif h[-1][0] != c["status"]:
            h.append([c["status"], stamp])
    hist_path.write_text(json.dumps(hist, indent=0, sort_keys=True))

    pulled = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (ROOT / "raw/jc_cases.json").write_text(json.dumps({"pulled": pulled, "cases": cases}))
    (ROOT / "raw/jc_agendas.json").write_text(json.dumps(ag))
    (ROOT / "data/agenda_index.json").write_text(json.dumps(sorted(agenda_ids), indent=0))
    print(f"wrote {len(cases)} cases, {len(ag)} agenda cases, {len(agenda_ids)} agendas")


if __name__ == "__main__":
    main()
