"""Who is behind each applicant: tidy names, then link LLCs to the developer behind them.

build.py calls clean_applicant() on every applicant name and link() once on all records. Nothing here fetches.

Evidence used, strongest first
  disclosure   the 10% owners on the case's ownership disclosure (N.J.S.A. 40:55D-48.1), read by applicants.py
  agency       a Redevelopment Agency resolution transferring the applicant's membership interests to another firm
  c/o          the company an agenda lists the applicant "in care of" ("626 Newark LLC c/o The Namdar Group")
  name         a known developer's name inside the LLC's own name ("Toll NJ I, L.L.C.")
LLCs that share an owner (a person or company with 10% or more) are one developer group. The group takes the name
of a known developer in it, else its most common owner(s), else the applicant itself.
"""
import re
from collections import Counter, defaultdict

# Developers active in Jersey City, recognised wherever they appear (LLC names, c/o lines, owner lists).
BRANDS = [
    (r"\bTOLL\b", "Toll Brothers"), (r"\bNAMDAR\b", "Namdar Group"), (r"\bKUSHNER\b|\bKRE\b", "Kushner / KRE"),
    (r"TISHMAN", "Tishman Speyer"), (r"MACK[- ]?CALI|\bVERIS\b|ROSELAND", "Veris (Mack-Cali)"), (r"\bCARLYLE\b", "The Carlyle Group"),
    (r"\bLE ?FRAK\b", "LeFrak"), (r"IRONSTATE", "Ironstate"), (r"\bSILVERMAN\b", "Silverman"), (r"\bBORAIE\b", "Boraie Development"),
    (r"\bALBANESE\b", "Albanese Organization"), (r"\bBIJOU\b", "Bijou Properties"), (r"\bPANEPINTO\b", "Panepinto Properties"),
    (r"\bVERMELLA\b", "Vermella Development"), (r"\bLENNAR\b", "Lennar"), (r"\bHARTZ\b", "Hartz Mountain"), (r"\bFIELDS\b", "Fields Development"),
    (r"\bBROOKFIELD\b|\bBSREP\b", "Brookfield"), (r"\bHUDSON EXCHANGE\b", "Hudson Exchange (Panepinto / Ironstate)"),
    (r"\bLINCOLN EQUITIES\b", "Lincoln Equities"), (r"\bWOODMONT\b", "Woodmont Properties"), (r"\bGARDEN HOMES\b", "Garden Homes"),
    (r"\bMACK REAL ESTATE\b", "Mack Real Estate"),
    (r"\bYAN MOSHE\b|HUDSON REGIONAL", "Hudson Regional Health (Yan Moshe)"), (r"\bTHIRD GATE\b", "Third Gate Capital"), (r"\bMILL CREEK RESIDENTIAL\b", "Mill Creek Residential"),
    (r"AVALONBAY|\bAVALON BAY\b", "AvalonBay"), (r"\bQUALITY PROPERTY\b", "Quality Property"),
]
_BRANDS = [(re.compile(rx, re.I), name) for rx, name in BRANDS if name]

ENTITY = re.compile(r"\b(L\.?\s?L\.?\s?C\.?|L\.?P\.?|INC\.?|CORP\.?|CORPORATION|COMPANY|CO\.|ASSOCIATES|URBAN RENEWAL|HOLDINGS|"
                    r"PARTNERS|TRUST|LTD\.?|GROUP|REALTY|PROPERTIES|DEVELOPMENT|DEVELOPERS|CAPITAL|EQUITIES|INVESTORS|VENTURES)\b", re.I)
LAW = re.compile(r"\b(ESQ|ESQUIRE|LAW|LLP|P\.?C\.|ATTORNEYS?|COUNSEL)\b", re.I)
# Land-use law firms whose names creep onto the front of an applicant ("Castano Quigley Cherami 626 Palisade Group, LLC").
FIRMS = re.compile(r"^(?:Castano Quigley(?:\s+Cherami)?|Connell Foley|Chiesa Shahinian(?:\s*&\s*Giantomasi)?|Genova Burns|McManimon,?\s*Scotland"
                   r"(?:\s*&\s*Baumann)?|Riker Danzig|Sills Cummis(?:\s*&\s*Gross)?|Wilentz|Day Pitney|Lum,?\s*Drasco(?:\s*&\s*Positan)?|"
                   r"Calli Law|Florio Kenny|Waters,?\s*McPherson|Inglesino|Prime\s*&\s*Tuvel|Weiner Law|Dario,?\s*Albert)\b[,\s]*", re.I)
NOT_OWNER = re.compile(r"^(jersey city|shareholders?|members?|partners?|see attached|n/?a|none|the applicant|applicant|hows\b)|"
                       r"\bjersey city,? n(?:ew )?j|^\W*$|^\d", re.I)


def _key(name):
    n = (name or "").upper().replace("&", " AND ")
    n = re.sub(r"\b(L\.?\s?L\.?\s?C|INC|CORP(?:ORATION)?|L\.?P|CO|COMPANY|LTD|THE)\b\.?", " ", n)
    n = re.sub(r"[^A-Z0-9 ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def brand_of(*texts):
    for t in texts:
        for rx, name in _BRANDS:
            if t and rx.search(t):
                return name
    return None


def clean_applicant(raw, attorney=""):
    """'626 Newark LLC c/o The Namdar Group' -> {'name': '626 Newark LLC', 'care_of': 'The Namdar Group'}.
    Also drops a law firm's name in front, '(represented by ...)', '..., by <signer>', trailing block/lot notes,
    and an applicant that is only the attorney ('Stephen Joseph, Esq.')."""
    s = re.sub(r"\s+", " ", raw or "").strip(" ,;")
    out = {"name": None, "care_of": None, "signer": None}
    if not s:
        return out
    s = re.sub(r"\s*\((?:represented|rep\.) by [^)]*\)", "", s, flags=re.I)
    s = re.sub(r"\s+on behalf of\b.*$", "", s, flags=re.I)
    m = re.search(r"\s*[,–-]?\s*\b(?:c/o|care of)\s+(.+)$", s, re.I)
    if m:
        out["care_of"] = m.group(1).strip(" ,.()")
        s = s[:m.start()]
    m = re.search(r",\s*by\s+([A-Z][^,]{3,40})$", s)
    if m:
        out["signer"] = m.group(1).strip()
        s = s[:m.start()]
    s = re.sub(r"\s*\((?=[^)]*\d)[^)]*\)\s*B:.*$|\s*\(?\bB:\s*\d.*$", "", s)          # "(236-238 Academy St) B: 12204 L: 23"
    s = re.sub(r"\s*\((?=[^)]*\d)[^)]*\)\s*$", "", s)
    stripped = FIRMS.sub("", s)
    if stripped != s and ENTITY.search(stripped):
        s = stripped
    elif attorney:
        last = (attorney.split(",")[0].split() or [""])[-1]
        if len(last) > 3 and s.upper().startswith(last.upper() + " ") and ENTITY.search(s[len(last):]):
            s = s[len(last):].strip()
    s = s.strip(" ,;-–")
    if not s or (LAW.search(s) and not ENTITY.search(re.sub(r"\bLAW\b.*", "", s, flags=re.I))):
        return out  # only the attorney or the law firm
    if out["care_of"] and LAW.search(out["care_of"]):
        out["care_of"] = None
    out["name"] = s
    return out


def owners_clean(owners):
    """Owners read off a disclosure, minus OCR debris and form labels; percentages kept."""
    seen, out = set(), []
    for o in owners or []:
        n = re.sub(r"^[\s|_]+", "", o.get("name") or "")
        n = re.sub(r"\s*\|.*$", "", n).strip(" ,;:-")
        n = re.sub(r"^\W+|\W+$", "", n)
        n = re.split(r"\s+(?:is|are|owns|owned|which|whose|holds|c/o|care of|approximately|\(the)\b", n, maxsplit=1, flags=re.I)[0].strip(" ,;:-")
        n = re.sub(r"^[a-h]\.\s+", "", n)
        n = re.sub(r"\s+(Jersey City|Hoboken|Brooklyn|New York),?.*$", "", n)
        if len(re.sub(r"[^A-Za-z]", "", n)) < 4 or NOT_OWNER.search(n):
            continue
        k = _key(n)
        if k in seen:
            continue
        seen.add(k)
        out.append({"name": n, "pct": o.get("pct"), "entity": bool(ENTITY.search(n))})
    return out


_TRANSFER = re.compile(r"TRANSFER OF (?:THE )?(?:MEMBERSHIP|OWNERSHIP) INTERESTS? IN ([A-Z0-9 ,.&'-]+?(?:LLC|L\.L\.C\.|INC)\.?),? "
                       r"TO ([A-Z0-9 ,.&'-]+?(?:LLC|L\.L\.C\.|INC|LP)\.?)(?=[, ]|$)", re.I)


def agency_transfers(items):
    """{applicant key: new owner} from Agency resolutions approving a transfer of membership interests."""
    out = {}
    for it in items:
        for m in _TRANSFER.finditer(it.get("title") or ""):
            out[_key(m.group(1))] = (m.group(2).strip(" ,."), it.get("date"))
    return out


def link(records, civic_items=()):
    """Sets on each record: developer (display name), dev_id, dev_basis (list of evidence), owners (public list)."""
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    transfers = agency_transfers(civic_items)
    names = defaultdict(Counter)   # group node -> display names seen
    basis = defaultdict(list)
    for r in records:
        app = r.get("applicant")
        if not app or not ENTITY.search(app):
            continue
        a = "E:" + _key(app)
        find(a)
        names[a][app] += 1
        for o in r.get("owners") or []:
            if o.get("pct") is not None and o["pct"] < 10:
                continue
            node = ("E:" if o["entity"] else "P:") + _key(o["name"])
            union(a, node)
            names[node][o["name"]] += 1
            basis[r["id"]].append("disclosure")
        if r.get("care_of") and ENTITY.search(r["care_of"]) or brand_of(r.get("care_of")):
            node = "E:" + _key(r["care_of"])
            union(a, node)
            names[node][r["care_of"]] += 1
            basis[r["id"]].append("c/o")
        t = transfers.get(_key(app))
        if t:
            node = "E:" + _key(t[0])
            union(a, node)
            names[node][t[0]] += 1
            basis[r["id"]].append("agency")
            r["transfer"] = {"to": t[0], "date": t[1]}
    groups = defaultdict(list)
    for r in records:
        app = r.get("applicant")
        if app and ENTITY.search(app):
            groups[find("E:" + _key(app))].append(r)
    members = defaultdict(set)
    for node in list(parent):
        members[find(node)].add(node)
    for root, rs in groups.items():
        nodes = members[root]
        all_names = [n for node in nodes for n in names[node]]
        brand = brand_of(*all_names)
        people = Counter()
        for node in nodes:
            if node.startswith("P:"):
                people[next(iter(names[node]))] += sum(names[node].values())
        owners_ent = Counter()
        for node in nodes:
            if node.startswith("E:") and not any(node == "E:" + _key(r["applicant"]) for r in rs):
                owners_ent[next(iter(names[node]))] += sum(names[node].values())
        if brand:
            name, how = brand, "name"
        elif owners_ent:
            name, how = owners_ent.most_common(1)[0][0], "owner"
        elif people:
            top = [p for p, _ in people.most_common(2)]
            name, how = " & ".join(top), "owner"
        else:
            name, how = Counter(r["applicant"] for r in rs).most_common(1)[0][0], "self"
        gid = "D:" + _key(name)[:60]
        linked = len({_key(r["applicant"]) for r in rs}) > 1 or how != "self"
        for r in rs:
            r["developer"] = name
            r["dev_id"] = gid
            r["dev_basis"] = sorted(set(basis.get(r["id"], []) + (["name"] if brand and brand_of(r["applicant"], r.get("care_of")) else [])))
            r["dev_linked"] = linked
            r["dev_people"] = [p for p, _ in people.most_common(4)]
    # A filing with no applicant named (an amendment, an extension) takes the developer of the other filings on its site.
    by_id = {r["id"]: r for r in records}
    for r in records:
        if r.get("dev_id"):
            continue
        sibs = sorted((by_id[i] for i in r.get("site_ids") or [] if i in by_id and by_id[i].get("dev_id")),
                      key=lambda q: q.get("applied") or "", reverse=True)
        if sibs:
            q = sibs[0]
            r.update(developer=q["developer"], dev_id=q["dev_id"], dev_linked=q.get("dev_linked"), dev_people=q.get("dev_people"),
                     dev_basis=["same site"])
            if q.get("transfer"):
                r["transfer"] = q["transfer"]
    return records
