"""Collect the Kushner Companies / KRE Group buildings listed in portfolio.json:
parcels, every planning/zoning case on those lots (any year), and their documents.

Cases come from the Jersey City permit portal (search by address, plus any case numbers listed in the config)
and from the Jersey City Open Data archive of pre-portal applications. Writes raw/portfolio.json.
"""
import json
import re
import sys
from pathlib import Path

import requests

import devmap

import fetch as F

ROOT = Path(__file__).parent


def parcel_at(lat, lon):
    r = requests.get(F.PARCELS, params={"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": "4326",
                     "spatialRel": "esriSpatialRelIntersects", "outFields": F.PFIELDS, "returnGeometry": "false",
                     "returnCentroid": "true", "outSR": "4326", "f": "json"}, timeout=60)
    feats = r.json().get("features") or []
    feats = [f for f in feats if (f["attributes"].get("PAMS_PIN") or "").startswith("0906_")]
    out = []
    for f in feats:
        a = f["attributes"]
        c = f.get("centroid") or {}
        a["lat"], a["lon"] = c.get("y"), c.get("x")
        out.append(a)
    return out


def address_cases(addr):
    """Portal cases whose address matches (any year)."""
    num, street = re.match(r"(\d+)\s+(.*)", addr).groups()
    street_key = re.sub(r"\b(avenue|ave|street|st|boulevard|blvd|drive|dr|plaza|plz|square|sq)\b\.?", "", street, flags=re.I).strip().upper()
    crit = F.get(F.API + "search/criteria").json()["Result"]
    b = json.loads(json.dumps(crit))
    b.update(Keyword=f"{num} {street_key}", SearchModule=1, FilterModule=3, PageNumber=1, PageSize=100, SortBy="relevance", SortAscending=False)
    b["PlanCriteria"].update(PlanTypeId="none", PlanStatusId="none")
    res = (F.post(F.API + "search/search", json=b).json().get("Result") or {}).get("EntityResults") or []
    hits = []
    for x in res:
        a = (x.get("AddressDisplay") or "").upper()
        if re.match(rf"^\s*{num}\b", a) and street_key.split()[0] in a and re.match(r"^[PZ]\d", x.get("CaseNumber") or ""):
            hits.append(x)
    return hits


def odp_by_address(addr):
    num, street = re.match(r"(\d+)\s+(.*)", addr).groups()
    word = street.split()[0].lower()
    q = requests.get("https://data.jerseycitynj.gov/api/explore/v2.1/catalog/datasets",
                     params={"where": f'search("{num} {word}")', "limit": 40, "select": "dataset_id,title"}, timeout=60).json()
    out = []
    for d in q.get("results", []):
        t = (d["title"] or "").lower()
        if re.search(rf"(?<!\d){num}(?:[-&]\d+)?\s+{re.escape(word)}", t) and re.search(r"\b[pz]\d{2,4}-\d{2,4}", t + " " + d["dataset_id"]):
            out.append(d)
    return out


def case_record(x):
    d = F.plan_detail(x["CaseId"])
    try:
        docs = F.attachments(x["CaseId"])
    except Exception:
        docs = []
    return {"id": x["CaseNumber"], "caseId": x["CaseId"], "type": x.get("CaseType"), "status": x.get("CaseStatus"),
            "applied": (x.get("ApplyDate") or "")[:10], "address": x.get("AddressDisplay"),
            "desc": re.sub(r"\s+", " ", d.get("Description") or x.get("Description") or "").strip(), "pin": d.get("MainParcelNumber"), "docs": docs}


def discover():
    """Every Jersey City parcel built since devmap.DISCOVER_SINCE whose tax description lists 100+ units."""
    rows, off = [], 0
    while True:
        r = requests.post(F.PARCELS, data={"where": f"PAMS_PIN LIKE '0906[_]%' AND YR_CONSTR >= {devmap.DISCOVER_SINCE} AND BLDG_DESC LIKE '%U%'",
                                           "outFields": F.PFIELDS, "returnGeometry": "false", "returnCentroid": "true", "outSR": "4326",
                                           "f": "json", "resultOffset": off, "resultRecordCount": 2000}, timeout=120)
        j = r.json()
        for f in j.get("features") or []:
            a = f["attributes"]
            c = f.get("centroid") or {}
            a["lat"], a["lon"] = c.get("y"), c.get("x")
            rows.append(a)
        if not j.get("exceededTransferLimit"):
            break
        off += 2000
    return rows


def main():
    cfg = json.loads((ROOT / "portfolio.json").read_text())
    try:
        found = discover()
        cfg["buildings"] = devmap.merge(cfg, found)
        print(f"tax records: {len(found)} rows, {sum(1 for b in cfg['buildings'] if b.get('discovered'))} buildings added to the curated list")
    except Exception as e:
        print("tax-record discovery failed; curated list only:", e, file=sys.stderr)
    out = []
    for b in cfg["buildings"]:
        rec = dict(b)
        pins, lots, cases, seen = [], [], [], set()
        # Lots given in the config (checked by hand) win over address matching, which can land on a same-named street.
        if b.get("pins"):
            got = F.parcels(b["pins"])
            for p_ in b["pins"]:
                if p_ in got:
                    pins.append(p_); lots.append(got[p_])
            if lots and "lat" not in b:
                rec["lat"], rec["lon"] = lots[0]["lat"], lots[0]["lon"]
        for addr in b["addresses"]:
            if not b.get("pins"):
                # Tax parcel by its street address first; the geocoder only when the tax rolls don't have the address.
                try:
                    pa = F.parcel_by_address(addr)
                except Exception:
                    pa = None
                if pa:
                    if pa["PAMS_PIN"] not in pins:
                        pins.append(pa["PAMS_PIN"]); lots.append(pa)
                    rec.setdefault("lat", pa["lat"]); rec.setdefault("lon", pa["lon"])
            g = None if (b.get("pins") or pins) else F.geocode(addr + ", Jersey City, NJ")
            if g and g["score"] >= 85:
                rec.setdefault("lat", g["lat"]); rec.setdefault("lon", g["lon"])
                for a in parcel_at(g["lat"], g["lon"]):
                    if a["PAMS_PIN"] not in pins:
                        pins.append(a["PAMS_PIN"]); lots.append(a)
            try:
                for x in address_cases(addr):
                    if x["CaseNumber"] not in seen:
                        seen.add(x["CaseNumber"]); cases.append(case_record(x))
            except Exception as e:
                print("portal search failed", addr, e, file=sys.stderr)
            try:
                for d in odp_by_address(addr):
                    m = re.search(r"\b([pz])(\d{2,4})-(\d{2,4})", (d["title"] + " " + d["dataset_id"]).lower())
                    cid = f"{m.group(1).upper()}{m.group(2)}-{m.group(3)}"
                    if any(c["id"].upper().replace("-0", "-") == cid.replace("-0", "-") for c in cases):
                        continue
                    o = F.odp_case(cid) or {}
                    if o:
                        cases.append({"id": cid, "type": (o.get("title") or "").split(" - ")[0], "status": "Archived", "applied": "",
                                      "address": addr, "desc": o.get("desc", "")[:1500], "odp": o, "docs": []})
                        seen.add(cid)
            except Exception as e:
                print("archive search failed", addr, e, file=sys.stderr)
        for cid in b.get("cases", []):
            if cid not in seen:
                x = F.find_case(cid)
                if x:
                    seen.add(cid); cases.append(case_record(x))
        rec["pins"], rec["lots"], rec["cases"] = pins, lots, cases
        print(f"{b['id']}: {len(pins)} lots, {len(cases)} cases, {sum(len(c.get('docs') or []) + len((c.get('odp') or {}).get('docs') or []) for c in cases)} documents")
        out.append(rec)
    (ROOT / "raw/portfolio.json").write_text(json.dumps(out))


if __name__ == "__main__":
    main()
