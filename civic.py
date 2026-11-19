"""Redevelopment Agency (JCRA) and City Council actions on tracked properties.

Run on its own (python civic.py) to refresh raw/civic.json.gz. build.py imports this module only for match_cases()
and public(), so nothing here runs on import.

Sources
  JCRA          board meeting agendas (thejcra.org, WordPress media library): every resolution and redeveloper
                presentation, which name the redeveloper, block, lot and street address.
  City Council  the Clerk's digital agendas (cityofjerseycity.civicweb.net), regular and special meetings since 2019:
                ordinances on first and second reading and resolutions, each with a link to its own PDF. Only the
                ones about redevelopment, tax abatements, zoning and city land are kept.

Matching to a property: the street address, the block and lot, or the applicant's company name in the item's text.
"""
import gzip
import html
import io
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import news as NEWS

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "raw/civic.json.gz"
UA = NEWS.UA
JCRA = "https://thejcra.org"
CW = "https://cityofjerseycity.civicweb.net"
COUNCIL_FOLDERS = {1021: "Regular meeting", 6957: "Special meeting"}
FIRST_YEAR = 2018

# Council items worth showing on a property.
NOT_RELEVANT = re.compile(r"lead (?:paint |based paint )?abatement|asbestos|noise abatement|appoint|reappoint|member of the", re.I)
RELEVANT = re.compile(r"redevelop|abatement|tax exemption|financial agreement|payment in lieu|\bPILOT\b|area in need|"
                      r"rehabilitation area|land development ordinance|zoning|zoning map|purchase and sale|sale of .{0,40}"
                      r"property|conveyance|ground lease|developer'?s agreement|community benefit", re.I)
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


# ------------------------------------------------------------------ cache
def load():
    if CACHE.exists():
        with gzip.open(CACHE, "rt", encoding="utf-8") as f:
            db = json.load(f)
    else:
        db = {}
    for k in ("items", "jcra_seen", "council_seen"):
        db.setdefault(k, {})
    return db


def save(db):
    CACHE.parent.mkdir(exist_ok=True)
    with gzip.open(CACHE, "wt", encoding="utf-8") as f:
        json.dump(db, f)


def _session():
    import requests
    s = requests.Session()
    s.headers["User-Agent"] = UA
    return s


def _clean(t):
    return re.sub(r"\s+", " ", t or "").strip()


# ------------------------------------------------------------------ JCRA
def _pdf_text(content, pages=40):
    """Text of a PDF; scanned agendas (no text layer, most JCRA agendas before 2025) are read with OCR."""
    import pdfplumber
    with pdfplumber.open(io.BytesIO(content)) as p:
        t = "\n".join((pg.extract_text() or "") for pg in p.pages[:pages])
    if len(t.strip()) > 200:
        return t
    try:
        import pypdfium2, pytesseract
        doc = pypdfium2.PdfDocument(content)
        out = []
        for i in range(min(len(doc), 12)):
            img = doc[i].render(scale=2.4).to_pil()
            out.append(pytesseract.image_to_string(img))
        return "\n".join(out)
    except Exception as e:
        print(f"  JCRA: OCR failed ({e})")
        return t


def _meeting_date(text, fallback):
    m = re.search(rf"({MONTHS})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d\d)", text[:1500])
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date().isoformat()
        except ValueError:
            pass
    return fallback


def jcra_items(text):
    """Resolutions ("Item #7 RESOLUTION ...") and redeveloper presentations ("A) X to make a presentation ...")."""
    out = []
    t = text.replace("\r", "")
    for m in re.finditer(r"(?:[Il]tem\s*(?:#|No\.?)?\s*\d+\s*[:.\-]?|^\s*\d{1,2}[.)]\s+|^\s*[a-h][.)]\s+)\s*(RESOLUTION\b.*?)"
                         r"(?=\n\s*[Il]tem\s*(?:#|No\.?)?\s*\d+|\n\s*\d{1,2}[.)]\s+[A-Z]|\n\s*[a-h][.)]\s+RESOLUTION|\Z)",
                         t, re.S | re.M):
        body = _clean(m.group(1))
        if re.search(r"minutes|executive session|public comment|league of municipalities|executive director|"
                     r"payment of (?:bills|invoices)|budget|audit|insurance|professional services", body[:220], re.I) \
                and not re.search(r"\bblock\b|\bredeveloper\b", body, re.I):
            continue
        out.append(("Resolution", body[:1200]))
    pres = re.search(r"PRESENTATIONS?\s*-?(.*?)(?=\n\s*\d{1,2}\.\s+[A-Z]|\n\s*Item\s*#)", t, re.S)
    if pres:
        for part in re.split(r"\n\s*[A-H]\)\s+", "\n" + pres.group(1)):
            body = _clean(part)
            if len(body) > 40 and re.search(r"present", body, re.I):
                out.append(("Presentation", body[:1200]))
    return out


def pull_jcra(db, S):
    page, pages, new = 1, 1, 0
    while page <= pages:
        r = S.get(f"{JCRA}/wp-json/wp/v2/media", timeout=60, params={
            "mime_type": "application/pdf", "per_page": 100, "page": page, "_fields": "id,date,source_url,title"})
        if r.status_code != 200:
            print(f"  JCRA: media page {page} returned {r.status_code}")
            break
        pages = int(r.headers.get("X-WP-TotalPages") or 1)
        for m in r.json():
            url, title = m["source_url"], _clean(html.unescape((m.get("title") or {}).get("rendered") or ""))
            name = url.rsplit("/", 1)[-1]
            if not re.search(r"agenda", name + " " + title, re.I) or re.search(r"annual|schedule|notice", name, re.I):
                continue
            if m["date"][:4] < str(FIRST_YEAR) or url in db["jcra_seen"]:
                continue
            try:
                f = S.get(url, timeout=120)
                text = _pdf_text(f.content) if f.ok else ""
            except Exception as e:
                print(f"  JCRA: {name} failed ({e})")
                continue
            date = _meeting_date(text, m["date"][:10])
            items = jcra_items(text)
            for i, (kind, body) in enumerate(items):
                db["items"][f"jcra:{m['id']}:{i}"] = {"src": "jcra", "kind": kind, "date": date, "title": body, "url": url,
                                                      "meeting": "Redevelopment Agency board"}
            db["jcra_seen"][url] = len(items)
            new += 1
            time.sleep(1.0)
        page += 1
    n = sum(1 for v in db["items"].values() if v["src"] == "jcra")
    print(f"  JCRA: {new} new agendas read; {n} resolutions and presentations on file")


# ------------------------------------------------------------------ City Council
def _folder(S, fid):
    r = S.get(f"{CW}/filepro/documents/{fid}/", timeout=60)
    return re.findall(r'data-id="(\d+)" data-parentid="\d+" data-order="\d+" data-type="(\w+)" data-title="([^"]*)"', r.text)


def council_items(page_html):
    """[(section, item no, title, label, pdf url)] from one digital agenda."""
    links = {}
    for href, label in re.findall(r'<a[^>]+href="(/document/\d+/[^"]+)"[^>]*>(.*?)</a>', page_html, re.S):
        lab = _clean(re.sub(r"<[^>]+>", " ", label))
        if re.match(r"(Ord|Res)\.", lab):
            links.setdefault(lab, CW + html.unescape(href))
    x = re.sub(r"<(script|style).*?</\1>", "", page_html, flags=re.S)
    x = re.sub(r"<br\s*/?>|</p>|</div>|</tr>|</td>|</li>|</h\d>|</a>", "\n", x)
    x = html.unescape(re.sub(r"<[^>]+>", " ", x)).replace("\xa0", " ")
    lines = [_clean(l) for l in x.split("\n")]
    lines = [l for l in lines if l]
    out, section, num, buf = [], "", None, []
    for l in lines:
        if re.fullmatch(r"(?:ORDINANCES?|RESOLUTIONS?)\b.*", l) and len(l) < 60:
            section = ("Ordinance, first reading" if "FIRST" in l else "Ordinance, second reading" if "SECOND" in l
                       else "Ordinance" if "ORDINANCE" in l else "Resolution")
            num, buf = None, []
            continue
        if re.fullmatch(r"\d{1,2}\.\d{1,3}", l):
            num, buf = l, []
            continue
        if re.fullmatch(r"\d+\s*-\s*\d+|\d+", l) or l in ("Page",):
            continue
        m = re.match(r"((?:Ord|Res)\.\s*\d{2}-\d{2,4})(.*)", l)
        if m and num and buf:
            label = l
            out.append((section, num, " ".join(buf), _clean(m.group(1)), "defeated" in m.group(2).lower(), links.get(label)))
            num, buf = None, []
            continue
        if num:
            buf.append(l)
    return out


def pull_council(db, S, budget=400):
    done = 0
    for fid, kind in COUNCIL_FOLDERS.items():
        for yid, typ, ytitle in _folder(S, fid):
            if typ != "folder" or not ytitle.isdigit() or int(ytitle) < FIRST_YEAR:
                continue
            for did, dtyp, dtitle in _folder(S, yid):
                if dtyp != "document" or not dtitle.endswith("Agenda - Html") or did in db["council_seen"]:
                    continue
                if done >= budget:
                    break
                m = re.search(r"- (\w{3})\w* (\d{1,2}) (20\d\d) -", dtitle)
                try:
                    date = datetime.strptime(" ".join(m.groups()), "%b %d %Y").date().isoformat() if m else None
                except ValueError:
                    date = None
                try:
                    r = S.get(f"{CW}/document/{did}/", timeout=120)
                except Exception as e:
                    print(f"  Council: agenda {did} failed ({e})")
                    continue
                if r.status_code != 200:
                    continue
                kept = 0
                for section, num, title, label, defeated, url in council_items(r.text):
                    if not RELEVANT.search(title) or NOT_RELEVANT.search(title):
                        continue
                    if label.startswith("Ord.") and not section.startswith("Ordinance"):
                        section = "Ordinance"
                    elif label.startswith("Res.") and section.startswith("Ordinance"):
                        section = "Resolution"
                    db["items"][f"council:{did}:{num}"] = {
                        "src": "council", "kind": section, "date": date, "title": title[:1500], "label": label,
                        "defeated": defeated, "url": url or f"{CW}/document/{did}/", "meeting": f"City Council · {kind}"}
                    kept += 1
                # A meeting still to come can gain addenda; read it again on later runs.
                if date and date < datetime.now().date().isoformat():
                    db["council_seen"][did] = kept
                done += 1
                time.sleep(0.8)
            time.sleep(0.5)
    n = sum(1 for v in db["items"].values() if v["src"] == "council")
    print(f"  Council: {done} agendas read; {n} redevelopment, abatement and zoning items on file")


# ------------------------------------------------------------------ matching
_BL = re.compile(r"Block\s*(\d{3,5}(?:\.\d{1,3})?)\s*,?\s*(?:Lots?|Lot\(s\))\s*([\d.,\s&and]+?\d)(?!\d)", re.I)
_LLC = re.compile(r"\b(?:L\.?L\.?C|INC|L\.?P|CORP(?:ORATION)?|URBAN RENEWAL|ASSOCIATES|COMPANY|CO)\b\.?", re.I)
_GENERIC = re.compile(r"JERSEY CITY|REDEVELOPMENT AGENCY|HOUSING AUTHORITY|BOARD OF EDUCATION|PORT AUTHORITY|COUNTY OF|"
                      r"STATE OF|NEW JERSEY TRANSIT|NJ TRANSIT|PSE&G|PUBLIC SERVICE", re.I)


def block_lots(text):
    out = set()
    for m in _BL.finditer(text or ""):
        for lot in re.findall(r"\d{1,4}(?:\.\d{1,3})?", m.group(2)):
            out.add((m.group(1).lstrip("0"), lot.lstrip("0") or "0"))
    return out


def _pin_bl(pin):
    p = (pin or "").split("_")
    return (p[1].lstrip("0"), p[2].lstrip("0") or "0") if len(p) >= 3 else None


def _entity(name):
    """'417 Communipaw OZ, LLC' -> '417 COMMUNIPAW OZ' (company names only, long enough to be specific)."""
    n = (name or "").upper()
    if not _LLC.search(n) or _GENERIC.search(n):
        return None
    n = _LLC.sub(" ", n)
    n = re.sub(r"[^A-Z0-9& ]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n if len(n) >= 8 and len(n.split()) >= 2 else None


def match_cases(cases, db=None):
    """{case id: [item id, ...]} newest first. Matched on the street address, the block and lot, or the applicant's
    company name; an item naming more than six sites is matched on the company name only."""
    db = db or load()
    addrs = {c["id"]: NEWS.case_addresses(c.get("address") or "") for c in cases}
    streets = {a[0] for v in addrs.values() for a in v}
    by_street, by_bl, by_ent = {}, {}, {}
    for c in cases:
        for a in addrs[c["id"]]:
            by_street.setdefault(a[0], []).append((a, c["id"]))
        for pin in c.get("parcel_pins") or [c.get("pams_pin")]:
            bl = _pin_bl(pin)
            if bl:
                by_bl.setdefault(bl, set()).add(c["id"])
        e = _entity(c.get("applicant"))
        if e:
            by_ent.setdefault(e, set()).add(c["id"])
    ent_re = re.compile(r"\b(" + "|".join(sorted(map(re.escape, by_ent), key=len, reverse=True)) + r")\b") if by_ent else None
    out, seen = {}, set()
    for iid, it in sorted(db["items"].items()):
        text = it["title"]
        # the same item on a revised agenda posted for the same meeting
        key = (it["src"], it.get("date"), re.sub(r"[^A-Z0-9]", "", text.upper())[:160])
        if key in seen:
            continue
        seen.add(key)
        hits = set()
        ms, bls = NEWS.mentions(text, streets), block_lots(text)
        # Contracts and grants that list many sites citywide (environmental work, fencing) aren't about any one of them.
        many = len({b for b, _ in bls}) > 6 or len(ms) > 6
        if not many:
            for m in ms:
                for a, cid in by_street.get(m[0], []):
                    if NEWS._same(a, m):
                        hits.add(cid)
            for bl in bls:
                hits |= by_bl.get(bl, set())
        if ent_re:
            up = re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9& ]", " ", _LLC.sub(" ", text.upper())))
            for m in ent_re.finditer(up):
                hits |= by_ent[m.group(1)]
        for cid in hits:
            out.setdefault(cid, []).append(iid)
    for cid in out:
        out[cid].sort(key=lambda i: db["items"][i].get("date") or "", reverse=True)
    return out


def public(it):
    return {k: it.get(k) for k in ("src", "kind", "date", "title", "url", "meeting", "label", "defeated") if it.get(k) is not None}


def main():
    db = load()
    S = _session()
    for name, step in (("JCRA", lambda: pull_jcra(db, S)), ("Council", lambda: pull_council(db, S))):
        try:
            step()
        except Exception as e:  # one source failing shouldn't stop the other
            print(f"  {name}: stopped ({type(e).__name__}: {e})")
        save(db)
    try:
        cases = json.loads((ROOT / "data/map.json").read_text(encoding="utf-8"))["cases"]
        m = match_cases(cases, db)
        print(f"civic: {len(db['items'])} items on file; {len({i for v in m.values() for i in v})} name a tracked property, covering {len(m)} cases")
    except Exception as e:
        print(f"civic: matching check skipped ({e})")


if __name__ == "__main__":
    sys.exit(main())
