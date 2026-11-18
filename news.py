"""News coverage of tracked properties: Jersey Digs, ROI-NJ, Real Estate NJ and Traded.

Run on its own (python news.py) to refresh raw/news.json.gz. build.py imports this module only for match_cases(),
so nothing here runs on import.

Sources
  Jersey Digs, ROI-NJ  WordPress feeds, every post mentioning "Jersey City" since 2018 (full text kept for matching).
  Traded               the site's deal sitemap; New Jersey deals whose address matches a tracked property, each page
                       read once to confirm it is in Jersey City and get its headline and date.
  Real Estate NJ       blocks automated readers, so it is searched through Google News, one tracked address at a time.
"""
import gzip
import html
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "raw/news.json.gz"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
SINCE = "2018-01-01T00:00:00"
OUTLETS = {"jd": "Jersey Digs", "roi": "ROI-NJ", "renj": "Real Estate NJ", "traded": "Traded"}

# ------------------------------------------------------------------ addresses
SUFFIX = {"AVENUE": "AVE", "AVE": "AVE", "AV": "AVE", "STREET": "ST", "ST": "ST", "BOULEVARD": "BLVD", "BLVD": "BLVD",
          "DRIVE": "DR", "DR": "DR", "PLACE": "PL", "PL": "PL", "ROAD": "RD", "RD": "RD", "TERRACE": "TER", "TER": "TER",
          "COURT": "CT", "CT": "CT", "LANE": "LN", "LN": "LN", "PARKWAY": "PKWY", "PKWY": "PKWY", "HIGHWAY": "HWY",
          "HWY": "HWY", "SQUARE": "SQ", "SQ": "SQ", "PLAZA": "PLZ", "PLZ": "PLZ", "WAY": "WAY", "CIRCLE": "CIR", "CIR": "CIR",
          "EXTENSION": "EXT", "EXT": "EXT"}
ORD = {"FIRST": "1ST", "SECOND": "2ND", "THIRD": "3RD", "FOURTH": "4TH", "FIFTH": "5TH", "SIXTH": "6TH", "SEVENTH": "7TH",
       "EIGHTH": "8TH", "NINTH": "9TH", "TENTH": "10TH", "ELEVENTH": "11TH", "TWELFTH": "12TH", "THIRTEENTH": "13TH",
       "FOURTEENTH": "14TH", "FIFTEENTH": "15TH", "SIXTEENTH": "16TH", "SEVENTEENTH": "17TH", "EIGHTEENTH": "18TH"}
# Several spellings of one street, reduced to one name.
ALIAS = [(r"\b(JOHN F KENNEDY|JOHN FITZGERALD KENNEDY|J F KENNEDY|JFK|KENNEDY)\b", "KENNEDY"),
         (r"\b(MARTIN LUTHER KING JR|MARTIN LUTHER KING|M L KING|MLK JR|MLK)\b", "MLK"),
         (r"\bSAINT\b", "ST"), (r"\bMOUNT\b", "MT"), (r"\bNEW JERSEY ROUTE\b|\bNJ ROUTE\b|\bRT\b", "ROUTE")]
CITY_TAIL = re.compile(r"(\s+JERSEY CITY)?(\s+(NEW JERSEY|NJ))?(\s+\d{5})?\s*$")


def _norm(s):
    s = html.unescape(s or "").upper().replace("’", "'").replace("–", "-").replace("—", "-").replace("½", ".5")
    s = re.sub(r"(\d)\.5\b", r"\1", s)            # 285.5 THIRD ST is lot 285.5, address 285
    s = re.sub(r"[.,'`]", " ", s)
    s = re.sub(r"[^A-Z0-9&\- ]", " ", s)
    s = re.sub(r"\s*-\s*", "-", " ".join(s.split()))
    for a, b in ALIAS:
        s = re.sub(a, b, s)
    return " ".join(ORD.get(w, w) for w in s.split())


def _core(words):
    """Street words -> (name, suffix). 'COMMUNIPAW AVE' -> ('COMMUNIPAW', 'AVE')."""
    words = [w for w in words if w]
    suf = None
    if words and words[-1] in SUFFIX:
        suf = SUFFIX[words[-1]]
        words = words[:-1]
    return " ".join(words), suf


def case_addresses(addr):
    """Every (street, suffix, lo, hi) a case address names: '415-421 COMMUNIPAW AVE AKA 10 WOODWARD ST' gives two,
    '286, 289 COLES STREET, 258-282 16TH STREET AND 311 & 312 17TH STREET' gives five."""
    s = CITY_TAIL.sub("", _norm(addr)).strip()
    s = re.sub(r"^(\d+) 440\b", r"\1 ROUTE 440", s)  # the portal writes "701 440" for 701 Route 440
    out, nums, words = [], [], []

    def flush():
        w = list(words)
        for i, x in enumerate(w[1:], 1):  # "PHILLIP STREET OLIVER STREET": the name ends at its first suffix
            if x in SUFFIX:
                w = w[: i + 1]
                break
        name, suf = _core(w)
        if nums and name and len(name) >= 3 and (suf or name not in SUFFIX) and not re.fullmatch(r"[\d ]+", name):
            out.extend((name, suf, lo, hi) for lo, hi in nums)

    prev = ""
    for tok in re.split(r"\s+|(?<=[A-Z0-9])(?=&)|(?<=&)", s.replace(",", " ")):
        p_, prev = prev, tok
        if not tok or tok in ("&", "AND", "AKA", "A", "K"):
            if tok == "AKA" and words:
                flush(); nums, words = [], []
            continue
        m = re.fullmatch(r"(\d+)[A-Z]?(?:-(\d+)[A-Z]?)?", tok)
        # a number right after a street word starts the next address, unless it is part of the name (ROUTE 440, 1ST)
        if m and p_ in ("SECTION", "BLOCK", "LOT", "LOTS", "UNIT", "PHASE", "BLDG", "BUILDING"):
            continue
        if m and not (p_ in ("ROUTE", "HWY", "HIGHWAY") or words and words[-1] in ("ROUTE", "HWY", "HIGHWAY")):
            if words:
                flush(); nums, words = [], []
            lo = int(m.group(1)); hi = int(m.group(2)) if m.group(2) else lo
            if hi < lo:  # 1017-19 means 1017-1019
                hi = int(str(lo)[: len(str(lo)) - len(m.group(2))] + m.group(2)) if m.group(2) else lo
            nums.append((lo, hi if 0 <= hi - lo < 200 else lo))
        elif nums:
            words.append(tok)
    if words:
        flush()
    return out


_W = r"(?:ROUTE \d+|[A-Z][A-Z0-9]*|\d+(?:ST|ND|RD|TH))"
_MENTION = re.compile(rf"\b(\d{{1,5}})[A-Z]?(?:\s*(?:-|&|AND|TO|THROUGH)\s*(\d{{1,5}})[A-Z]?)?\s+((?:{_W}\s+){{0,4}}{_W})")


def mentions(text, streets):
    """Addresses on known streets in a piece of text: {(street, suffix-or-None, lo, hi)}."""
    s = _norm(text)
    found = set()
    for m in _MENTION.finditer(s):
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        if hi < lo or hi - lo > 200:
            hi = lo
        words = m.group(3).split()
        # the longest run of words that is a tracked street name
        for k in range(min(len(words), 4), 0, -1):
            name = " ".join(words[:k])
            if name in streets:
                suf = SUFFIX.get(words[k]) if k < len(words) else None
                if suf or not 1900 <= lo <= 2099:  # "in 2023 Communipaw..." is a year
                    found.add((name, suf, lo, hi))
                break
    return found


def _same(a, b):
    """A tracked address and an address in an article name the same place."""
    return a[0] == b[0] and (not a[1] or not b[1] or a[1] == b[1]) and a[2] <= b[3] and b[2] <= a[3]


# ------------------------------------------------------------------ cache
def load():
    if CACHE.exists():
        try:
            return json.loads(gzip.decompress(CACHE.read_bytes()))
        except Exception:
            pass
    return {"articles": {}, "wp_newest": {}, "traded_seen": {}, "gnews_tried": {}}


def save(db):
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_bytes(gzip.compress(json.dumps(db, separators=(",", ":")).encode()))


def _text(h):
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h or "", flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


# ------------------------------------------------------------------ matching (used by build.py)
def match_cases(cases, db=None):
    """{case id: [article, ...]} newest first. An article counts when it names the case's address (number on the same
    street, ranges overlapping) and, for the WordPress outlets, mentions Jersey City."""
    db = db or load()
    addrs = {c["id"]: case_addresses(c.get("address") or "") for c in cases}
    streets = {a[0] for v in addrs.values() for a in v}
    by_street = {}
    for cid, v in addrs.items():
        for a in v:
            by_street.setdefault(a[0], []).append((a, cid))
    out = {}
    for aid, art in db["articles"].items():
        if art["src"] in ("jd", "roi") and "JERSEY CITY" not in (art.get("text") or "").upper() + art["title"].upper():
            continue
        if art["src"] in ("renj", "traded"):
            hits = {cid for cid in art.get("cases") or []}
            # a search hit is kept only while the address it was found for is still tracked
            hits = {cid for cid in hits if cid in addrs}
        else:
            hits = set()
            for m in mentions(art["title"] + " . " + (art.get("text") or ""), streets):
                for a, cid in by_street.get(m[0], []):
                    if _same(a, m):
                        hits.add(cid)
        for cid in hits:
            out.setdefault(cid, []).append(aid)
    for cid in out:
        out[cid].sort(key=lambda i: db["articles"][i]["date"] or "", reverse=True)
    return out


def public(art):
    """What the page shows for an article."""
    return {"src": OUTLETS[art["src"]], "title": art["title"], "date": (art["date"] or "")[:10], "url": art["url"],
            "blurb": (art.get("blurb") or "")[:260]}


# ------------------------------------------------------------------ fetching
def _session():
    import requests
    s = requests.Session()
    s.headers["User-Agent"] = UA
    return s


def pull_wordpress(db, S, key, base):
    """Every post mentioning Jersey City since 2018 on the first run; afterwards only posts since the newest seen."""
    since = db["wp_newest"].get(key)
    after = (datetime.fromisoformat(since) - timedelta(days=3)).isoformat() if since else SINCE
    page, added, pages = 1, 0, None
    while True:
        try:
            r = S.get(f"{base}/wp-json/wp/v2/posts", timeout=60, params={
                "search": "Jersey City", "after": after, "per_page": 100, "page": page, "orderby": "date", "order": "asc",
                "_fields": "id,date,link,title,excerpt,content"})
        except Exception as e:
            print(f"  {key}: page {page} failed ({e})"); break
        if r.status_code == 400:  # past the last page
            break
        if r.status_code != 200:
            print(f"  {key}: page {page} returned {r.status_code}"); break
        pages = pages or int(r.headers.get("X-WP-TotalPages") or 1)
        for p in r.json():
            aid = f"{key}:{p['id']}"
            db["articles"][aid] = {"src": key, "title": _text(p["title"]["rendered"]), "date": p["date"], "url": p["link"],
                                   "blurb": _text(p["excerpt"]["rendered"]), "text": _text(p["content"]["rendered"])[:20000]}
            added += 1
            db["wp_newest"][key] = max(db["wp_newest"].get(key) or "", p["date"])
        if page >= pages:
            break
        page += 1
        time.sleep(0.7)
    print(f"  {OUTLETS[key]}: {added} posts read (since {after[:10]}, {pages or 0} pages)")


def _tracked(cases):
    """Distinct (number, street) pairs of tracked cases -> case ids, plus the street names."""
    pairs = {}
    for c in cases:
        for name, suf, lo, hi in case_addresses(c.get("address") or ""):
            pairs.setdefault((lo, name, suf), set()).add(c["id"])
    return pairs


def pull_traded(db, S, cases, budget=250):
    """New Jersey deals in Traded's sitemap whose address is a tracked one; each candidate page read once."""
    pairs = _tracked(cases)
    streets = {k[1] for k in pairs}
    by_street = {}
    for (n, name, suf), ids in pairs.items():
        by_street.setdefault(name, []).append(((name, suf, n, n), ids))
    urls = []
    try:
        idx = S.get("https://traded.co/sitemap.xml", timeout=60).text
        for sm in re.findall(r"<loc>(https://traded\.co/sitemap-deals(?:-\d+)?\.xml)</loc>", idx):
            body = S.get(sm, timeout=120).text
            urls += re.findall(r"<loc>(https://traded\.co/deals/new-jersey/[^<]+)</loc>", body)
    except Exception as e:
        print(f"  Traded: sitemap failed ({e})"); return
    cand = {}
    for u in urls:
        slug = u.rstrip("/").rsplit("/", 1)[-1]
        slug = re.sub(r"-\d+$", "", slug) if re.match(r"^\d", slug) else slug  # "70-mallory-avenue-2" is a 2nd deal
        for m in mentions(slug.replace("-", " "), streets):
            ids = set()
            for a, cid in by_street.get(m[0], []):
                if _same(a, m):
                    ids |= cid
            if ids:
                cand[u] = sorted(ids)
    print(f"  Traded: {len(urls)} New Jersey deals, {len(cand)} name a tracked address")
    done = 0
    for u, ids in cand.items():
        seen = db["traded_seen"].get(u)
        if seen is not None:
            if seen and seen in db["articles"]:
                db["articles"][seen]["cases"] = ids
            continue
        if done >= budget:
            break
        done += 1
        try:
            h = S.get(u, timeout=60).text
        except Exception:
            continue
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
        try:
            deal = json.loads(m.group(1))["props"]["pageProps"]["deal"]
        except Exception:
            deal = None
        if not deal or not any((p.get("city") or "").lower() == "jersey city" for p in deal.get("properties") or []):
            db["traded_seen"][u] = ""
            continue
        price = deal.get("salePrice")
        bits = [deal.get("assetType"), deal.get("transactionType"), f"${price:,.0f}" if price else None, deal.get("parties")]
        aid = "traded:" + str(deal.get("id") or u)
        db["articles"][aid] = {"src": "traded", "title": deal.get("articleTitle") or deal.get("title") or u,
                               "date": (deal.get("closingDate") or deal.get("publishedAt") or "")[:10] or None, "url": u,
                               "blurb": " · ".join(b for b in bits if b), "cases": ids}
        db["traded_seen"][u] = aid
        time.sleep(0.6)
    print(f"  Traded: read {done} deal pages")


def pull_renj(db, S, cases, budget=300):
    """Real Estate NJ through Google News, one tracked address at a time; each address searched again after 30 days
    (60 for cases already closed)."""
    pairs = _tracked(cases)
    status = {c["id"]: c.get("stage") for c in cases}
    now = datetime.now(timezone.utc)
    todo = []
    for (n, name, suf), ids in pairs.items():
        if len(name) < 4 and not suf:
            continue
        q = f'"{n} {name.title()}"'
        last = db["gnews_tried"].get(q)
        open_ = any(status.get(i) in ("filed", "review", "scheduled", "heard") for i in ids)
        if last and (now - datetime.fromisoformat(last)).days < (30 if open_ else 60):
            continue
        todo.append((last or "", q, sorted(ids)))
    todo.sort()  # never-searched first, then the longest ago
    done = hits = 0
    for _, q, ids in todo[:budget]:
        url = ("https://news.google.com/rss/search?q=" + quote_plus(f'{q} "Jersey City" site:re-nj.com')
               + "&hl=en-US&gl=US&ceid=US:en")
        try:
            r = S.get(url, timeout=30)
        except Exception:
            continue
        if r.status_code == 429 or r.status_code >= 500:
            print(f"  Real Estate NJ: Google News stopped answering ({r.status_code}) after {done} searches"); break
        done += 1
        db["gnews_tried"][q] = now.isoformat()
        for it in re.findall(r"<item>(.*?)</item>", r.text, re.S):
            g = lambda t: html.unescape((re.search(rf"<{t}[^>]*>(.*?)</{t}>", it, re.S) or [None, ""])[1]).strip()
            title, link, pub = g("title"), g("link"), g("pubDate")
            title = re.sub(r"\s+-\s+Real Estate NJ\s*$", "", title)
            try:
                date = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z").date().isoformat()
            except ValueError:
                date = None
            aid = "renj:" + re.sub(r"\W+", "-", title.lower())[:90]
            art = db["articles"].setdefault(aid, {"src": "renj", "title": title, "date": date, "url": link, "blurb": "", "cases": []})
            art["cases"] = sorted(set(art.get("cases") or []) | set(ids))
            hits += 1
        time.sleep(2.0)
    print(f"  Real Estate NJ: {done} of {len(todo)} addresses searched, {hits} article hits")


def main():
    cases = json.loads((ROOT / "data/map.json").read_text(encoding="utf-8"))["cases"]
    db = load()
    S = _session()
    pull_wordpress(db, S, "jd", "https://jerseydigs.com")
    save(db)
    pull_wordpress(db, S, "roi", "https://www.roi-nj.com")
    save(db)
    pull_traded(db, S, cases)
    save(db)
    pull_renj(db, S, cases)
    save(db)
    m = match_cases(cases, db)
    n_art = len({a for v in m.values() for a in v})
    print(f"news: {len(db['articles'])} articles on file; {n_art} name a tracked property, covering {len(m)} cases")


if __name__ == "__main__":
    sys.exit(main())
