"""Developer map: curated buildings (portfolio.json) plus every large new building found in the state tax records.

Discovery: every Jersey City tax parcel built in DISCOVER_SINCE or later whose MOD-IV building description lists
DISCOVER_MIN_UNITS or more units ("50S-C-447U"). Condo regimes list one row per unit, so rows are folded into one
building per lot and unit count. A discovered building that matches a curated one (same parcel, or same street
address) is skipped; the rest are added. Their developer comes from portfolio.json:
  - "known": a researched attribution for one address, with sources;
  - "mail_rules": the tax bill's mailing address, which is the owner's office (e.g. KRE's in Bridgewater);
  - otherwise "Developer not yet identified", with the tax-bill address shown.
"""
import re

DISCOVER_SINCE = 2010
DISCOVER_MIN_UNITS = 100


def units_of(desc):
    m = re.search(r"(\d{3,4})\s*U\b", desc or "")
    return int(m.group(1)) if m else 0


def stories_of(desc):
    m = re.match(r"\s*(\d{1,2})S", desc or "")
    return int(m.group(1)) if m else None


def addr_key(a):
    a = re.sub(r"[.,]", " ", (a or "").upper())
    a = re.sub(r"\b(STREET|ST|AVENUE|AVE|BOULEVARD|BLVD|DRIVE|DR|PLACE|PL|ROAD|RD|LANE|LN|PLAZA|SQUARE|SQ)\b", "", a)
    a = a.replace("CHRISTOPHER COLUMBUS", "COLUMBUS").replace("TENTH", "10TH").replace("SIXTEENTH", "16TH").replace("FIFTEENTH", "15TH")
    a = a.replace("SECOND", "2ND").replace("FIRST", "1ST").replace("AVENUE", "")
    return " ".join(a.split())


def title(s):
    s = " ".join(w.capitalize() for w in (s or "").lower().split())
    s = re.sub(r"\b(\d+)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), s)
    return re.sub(r"\b(Blvd|Ave|St|Dr|Pl|Ln|Rd)\b", lambda m: m.group(1) + ".", s).replace("..", ".")


def fold(rows):
    """MOD-IV rows -> one record per building (lot + unit count), keeping the base lot over condo unit rows."""
    by = {}
    for a in rows:
        u = units_of(a.get("BLDG_DESC"))
        yr = int(a.get("YR_CONSTR") or 0)
        if u < DISCOVER_MIN_UNITS or yr < DISCOVER_SINCE:
            continue
        pin = a["PAMS_PIN"]
        parts = pin.split("_")
        key = (parts[1], parts[2], u)
        cur = by.get(key)
        if cur is None or ("_C" in cur["PAMS_PIN"] and "_C" not in pin):
            by[key] = a
    # Same street address listed twice (two condo regimes in one tower): keep the larger.
    out = {}
    for a in by.values():
        k = addr_key(a.get("PROP_LOC"))
        if k not in out or units_of(a["BLDG_DESC"]) > units_of(out[k]["BLDG_DESC"]):
            out[k] = a
    return sorted(out.values(), key=lambda a: -units_of(a["BLDG_DESC"]))


def merge(cfg, rows):
    """Curated buildings + discovered ones. Returns the full building list (curated first)."""
    curated = list(cfg["buildings"])
    have_pins = {p for b in curated for p in b.get("pins") or []}
    have_addr = {addr_key(a) for b in curated for a in b.get("addresses") or []}
    known = {addr_key(k): v for k, v in (cfg.get("known") or {}).items()}
    rules = cfg.get("mail_rules") or []
    out = list(curated)
    for a in fold(rows):
        pin, loc = a["PAMS_PIN"], a.get("PROP_LOC") or ""
        if pin in have_pins or addr_key(loc) in have_addr:
            continue
        mail = ", ".join(x for x in [(a.get("ST_ADDRESS") or "").strip(), (a.get("CITY_STATE") or "").strip()] if x)
        u, st, yr = units_of(a["BLDG_DESC"]), stories_of(a["BLDG_DESC"]), int(a.get("YR_CONSTR") or 0)
        k = known.get(addr_key(loc))
        devs, sources, name, note = None, [], None, ""
        if k:
            devs, sources, name, note = k["developers"], k.get("sources") or [], k.get("name"), k.get("note") or ""
        else:
            up = re.sub(r"[^A-Z0-9 ]", "", mail.upper())
            for r in rules:
                if any(m in up for m in r["match"]):
                    devs = [{"key": r["key"], "role": r.get("role") or "Owner (tax-bill address)"}]
                    note = r.get("note") or ""
                    break
        if not devs:
            devs = [{"key": "other", "role": "Developer not yet identified"}]
        summary = f"From the NJ tax record: {st or '?'} stories, {u} units, built {yr}. Tax bill goes to {title(mail) or 'an address not listed'}."
        if note:
            summary = note + " " + summary
        out.append({
            "id": "t-" + pin.split("_", 1)[1].replace("_", "-").replace(".", "-").lower(),
            "name": name or title(loc), "company": devs[0]["key"], "developers": devs, "partners": [],
            "addresses": [title(loc)], "units": u, "stories": st, "completed": str(yr), "status": "Completed",
            "summary": summary, "sources": sources, "pins": [pin], "lat": a.get("lat"), "lon": a.get("lon"),
            "owner_mail": mail, "discovered": True,
        })
    return out
