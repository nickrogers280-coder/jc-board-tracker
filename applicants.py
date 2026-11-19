"""Applicant (and attorney) for cases the board agendas haven't named yet, read from the case's own filings.

Every application carries the city's General Development Application form ("11. Applicant Name: ...",
"25. Attorney's Name: ...") and, for companies, the 10% ownership disclosure required by N.J.S.A. 40:55D-48.1
("APPLICANT: 38 Van Reipen Owner LLC" plus the 10% owners). This reads those PDFs - from the verified copies on
the releases when there is one, otherwise straight from the city portal - and records what it finds in
raw/applicants.json: {case: {applicant, attorney, source, doc, owners, checked}}.

Owners are kept for the next step (business-entity lookups) but not shown yet. Cases are re-read only when a
newer form is filed. Budget-limited per run; the rest follow on later runs.
"""
import io
import json
import re
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import requests

import docs_mirror as DM

ROOT = Path(__file__).parent
BUDGET = 500          # forms read per run
OWNER_BUDGET = 300    # ownership disclosures read per run for company applicants already named
FORM = [  # which filings to read, best first
    ("disclosure", re.compile(r"disclos", re.I)),
    ("application form", re.compile(r"general development application|\bGDA\b(?!_?checklist)|planning application|development application|application form|appeal application", re.I)),
    ("affidavit of ownership", re.compile(r"affidavit of (ownership|control)", re.I)),
    ("board resolution", re.compile(r"^RESO\b|resolution", re.I)),
]
PV = 2  # parser version: records from older parsers are re-read
ENTITY = re.compile(r"\b(L\.?\s?L\.?\s?C\.?|L\.?P\.?|INC\.?|CORP\.?|CORPORATION|COMPANY|CO\.|ASSOCIATES|URBAN RENEWAL|HOLDINGS|PARTNERS|TRUST|LTD\.?|GROUP|REALTY|PROPERTIES|DEVELOPMENT|AUTHORITY|UNIVERSITY|CHURCH|BOARD OF EDUCATION|CITY OF)\b", re.I)


def fix_split(v):
    """Filled-in form values come out of the PDF with a space after the first letter: 'J ersey City', 'N EQ 8A LLC'."""
    v = v.strip()
    m = re.match(r"^([A-Za-z0-9(])\s(\S)", v)
    if m and not (m.group(1) in "AI" and m.group(2).isupper() and len(v.split()[1]) > 1 and v.split()[1][1:2].islower()):
        v = m.group(1) + v[2:]
    return v


def clean(v):
    v = fix_split(re.sub(r"\s+", " ", v or "")).strip(" ,;:-")
    v = re.sub(r"^(Applicant(?:'s)?|Name|Owner)\s*[;:,.]?\s*", "", v, flags=re.I)  # OCR keeps the label sometimes
    v = re.sub(r"\b(Same as (the )?applicant|Owner|N/?A|See attached.*|TBD)$", "", v, flags=re.I).strip(" ,;:-")
    if not v or len(v) < 3 or re.fullmatch(r"(n/?a|none|same|tbd|see attached.*)", v, re.I):
        return None
    v = re.sub(r"\s+(Owner|Applicant)\.?$", "", v, flags=re.I).strip(" ,;:-")
    return v[:120] if len(v) >= 3 else None


JUNK = re.compile(r"street address|subject property|application for development|percentage|firm'?s name|not applicable|"
                  r"town/city|required for|^\W*\d+\W*$|^(llc|inc|n|c)$|[|\\]|architect\b|\bR\.A\.|design studio|"
                  r"^(owner|applicant|name)\b|^\d+\.\s", re.I)
SUFFIX = re.compile(r"\b(LLC|L\.L\.C|Inc|Corp|LP|L\.P|Co)\.?,?$", re.I)


def tidy(v, kind="applicant"):
    """Final clean-up of a name read off a form; None when it isn't a name (a form label, an address, an architect)."""
    if not v:
        return None
    v = re.sub(r"\s+", " ", v).strip(" _|,;:-")
    v = re.sub(r"^(OF ENTITY|Re|RE)\s*:\s*", "", v)
    m = re.search(r"(?:this office represents|I am counsel to)\s+(.+?)(?:,\s*(?:the|and)\b|$)", v, re.I)
    if m:
        v = m.group(1)
    v = re.sub(r"^.*?\bNJ\s+\d{5}\s+", "", v)                      # leading street address
    v = re.sub(r"\s+\d{1,3}(\.\d+)?\s*%.*$", "", v)                 # trailing ownership share
    v = re.split(r"\s+Own(?:er|et)\s*:", v, flags=re.I)[0]             # "X LLC Owner: X LLC"
    parts = re.split(r"\s+Own(?:er|et)\s+", v, maxsplit=1, flags=re.I)  # applicant and owner side by side
    if len(parts) == 2 and (SUFFIX.search(parts[0]) or re.match(r"\d", parts[1])):
        v = parts[0]
    v = re.sub(r",?\s+c/o\b.*$", "", v, flags=re.I)
    w = v.split()
    for n in range(len(w) // 2, 1, -1):                                # "X LLC X LLC" -> "X LLC"
        if len(w) == 2 * n and [x.lower() for x in w[:n]] == [x.lower() for x in w[n:]]:
            v = " ".join(w[:n])
            break
    if len(w) == 2 * (len(w) // 2) and len(w) >= 4 and re.sub(r"\W", "", " ".join(w[:len(w)//2])).lower() == re.sub(r"\W", "", " ".join(w[len(w)//2:])).lower():
        v = " ".join(w[len(w) // 2:])
    v = v.strip(" ,;:-.") + ("." if re.search(r"\b(Inc|Corp|Co|L\.L\.C|L\.P)$", v.strip(" ,;:-.")) else "")
    if len(re.sub(r"[^A-Za-z]", "", v)) < 3 or JUNK.search(v):
        return None
    if kind == "applicant" and re.fullmatch(r"city of jersey city", v, re.I):
        return None  # the form's own letterhead; real city filings are named on the agendas
    if kind == "attorney" and (len(v) < 5 or not re.search(r"[a-z]", v)):
        return None
    return v[:120]


def parse(text, label="disclosure"):
    """Applicant, attorney and 10% owners from a GDA form or an ownership disclosure."""
    t = text.replace("’", "'")
    lines = [l.strip() for l in t.splitlines() if l.strip()]
    out = {"applicant": None, "attorney": None, "owners": []}
    m = re.search(r"Applicant(?:'s)?\s*Name\s*:?\s*(.+)", t, re.I) or re.search(r"APPLICANT\s*(?:/\s*OWNER)?\s*:\s*(\S.+)", t)
    if m:
        out["applicant"] = clean(m.group(1))
    if not out["applicant"]:
        # Disclosure forms where the filled-in value sits on the line above its label ("44 Coles SPE, LLC ... / Applicant:").
        for i, l in enumerate(lines):
            if re.match(r"^Applicant\s*:", l, re.I) and i:
                cand = re.split(r"\s{2,}|Same as", lines[i - 1])[0]
                if ENTITY.search(cand):
                    out["applicant"] = clean(cand)
                    break
    if not out["applicant"] and label in ("disclosure", "application form"):  # resolutions etc.: labelled values only
        for l in lines[:40]:
            if ENTITY.search(l) and not re.search(r"jersey city planning|board of adjustment|n\.j\.s\.a|disclosure|stockholder|partnership|corporation or", l, re.I):
                out["applicant"] = clean(re.split(r"\s{2,}", l)[0])
                if out["applicant"]:
                    break
    m = re.search(r"Attorney(?:'s)?\s*Name\s*:?\s*(.+)", t, re.I)
    if m:
        out["attorney"] = clean(m.group(1))
    is_disclosure = bool(re.search(r"disclosure|40:55D-48", t[:600], re.I)) and not re.search(r"GENERAL DEVELOPMENT\s+APPLICATION", t[:800], re.I)
    for l in lines if is_disclosure else []:
        if re.match(r"^[\d*(]", l):
            continue
        pm = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", re.sub(r"(\d)\s+(\d)", r"\1\2", l))
        if not pm or re.search(r"at least|10%|ten percent|percentage|ownership interest", l, re.I):
            continue
        name = re.split(r"\s\d", l)[0].strip(" ,")
        if 3 <= len(name) <= 80 and re.search(r"[A-Za-z]{2}", name) and 0 < float(pm.group(1)) <= 100 and not re.search(r"[()%]", name):
            out["owners"].append({"name": fix_split(name), "pct": float(pm.group(1))})
    out["applicant"] = tidy(out["applicant"])
    out["attorney"] = tidy(out["attorney"], "attorney")
    return out


def text_of(path):
    """Text of the first pages; scanned forms (no text layer) are read with OCR."""
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        t = "\n".join((p.extract_text() or "") for p in pdf.pages[:4])
    if len(t.strip()) > 40:
        return t
    try:
        import pypdfium2
        import pytesseract
        doc = pypdfium2.PdfDocument(str(path))
        out = []
        for i in range(min(3, len(doc))):
            img = doc[i].render(scale=2.5).to_pil()
            out.append(pytesseract.image_to_string(img))
        return "\n".join(out)
    except Exception as e:
        print("OCR unavailable:", e, file=sys.stderr)
        return t


def main():
    cases = json.loads((ROOT / "raw/jc_cases.json").read_text())["cases"]
    agendas = json.loads((ROOT / "raw/jc_agendas.json").read_text()) if (ROOT / "raw/jc_agendas.json").exists() else {}
    mirror = json.loads((ROOT / "data/mirror.json").read_text()) if (ROOT / "data/mirror.json").exists() else {}
    vpath = ROOT / "raw/mirror_verified.json"
    verified = json.loads(vpath.read_text()) if vpath.exists() else {}
    apath = ROOT / "raw/applicants.json"
    found = json.loads(apath.read_text()) if apath.exists() else {}

    todo = []
    for c in cases:
        if (agendas.get(c["id"]) or {}).get("app"):
            continue  # named on a board agenda already
        forms = []
        for label, rx in FORM:
            for d in sorted(c.get("docs") or [], key=lambda d: d.get("added") or "", reverse=True):
                if d.get("id") and rx.search(d.get("name") or "") and re.search(r"\.pdf$", d.get("name") or "", re.I):
                    forms.append((label, d))
        if not forms:
            continue
        prev = found.get(c["id"]) or {}
        if prev.get("pv") != PV:
            prev = {}
        newest = max(d.get("added") or "" for _, d in forms)
        if prev.get("applicant") and prev.get("newest", "") >= newest:
            continue
        if prev.get("tried", "") >= newest and not prev.get("applicant") and prev.get("tries", 0) >= len(forms):
            continue
        todo.append((c, forms, newest))
    todo.sort(key=lambda x: x[0].get("applied") or "", reverse=True)  # newest filings first
    print(f"applicants: {len(todo)} cases to read from their filings")

    s = requests.Session()
    DM.warm(s)
    read = named = 0
    for c, forms, newest in todo:
        if read >= BUDGET:
            break
        rec = {"checked": date.today().isoformat(), "newest": newest, "tried": newest, "tries": 0, "pv": PV,
               "applicant": None, "attorney": None, "source": None, "doc": None, "owners": []}
        for label, d in forms:
            if read >= BUDGET:
                break
            rec["tries"] += 1
            read += 1
            try:
                with tempfile.TemporaryDirectory() as td:
                    path = Path(td) / "f.pdf"
                    m = mirror.get(d["id"])
                    if m and verified.get(d["id"]) == m["asset"]:
                        r = requests.get(f"https://github.com/{DM.REPO}/releases/download/{m.get('tag', 'documents')}/{m['asset']}", timeout=120)
                        r.raise_for_status()
                        path.write_bytes(r.content)
                    else:
                        DM.download(s, d["id"], path)
                        time.sleep(0.6)
                    got = parse(text_of(path), label)
            except Exception as e:
                print("could not read", c["id"], d.get("name"), e, file=sys.stderr)
                continue
            if got["applicant"] and not rec.get("applicant"):
                rec.update(applicant=got["applicant"], source=label, doc=d.get("name"))
            if got["attorney"] and not rec.get("attorney"):
                rec["attorney"] = got["attorney"]
            if got["owners"] and not rec.get("owners"):
                rec["owners"] = got["owners"][:12]
            if rec.get("applicant") and (rec.get("attorney") or label == "application form"):
                break
        if rec.get("applicant"):
            named += 1
        found[c["id"]] = rec
    apath.write_text(json.dumps(found))
    print(f"applicants: read {read} forms, named {named} cases this run, {sum(1 for v in found.values() if v.get('applicant'))} named in all")

    # Second pass: the 10% owners behind every company applicant, including the ones a board agenda already named
    # (the agenda gives the LLC; only the disclosure says who is behind it). Feeds the developer links in parents.py.
    dis = FORM[0][1]
    todo2 = []
    for c in cases:
        prev = found.get(c["id"]) or {}
        app = (agendas.get(c["id"]) or {}).get("app") or prev.get("applicant") or ""
        if prev.get("owners") or not ENTITY.search(app):
            continue
        ds = [d for d in sorted(c.get("docs") or [], key=lambda d: d.get("added") or "", reverse=True)
              if d.get("id") and dis.search(d.get("name") or "") and re.search(r"\.pdf$", d.get("name") or "", re.I)]
        if not ds or prev.get("owners_tried", "") >= (ds[0].get("added") or ""):
            continue
        todo2.append((c, ds[:2]))
    todo2.sort(key=lambda x: x[0].get("applied") or "", reverse=True)
    print(f"owners: {len(todo2)} company applicants with a disclosure not read yet")
    got_n = read2 = 0
    for c, ds in todo2:
        if read2 >= OWNER_BUDGET:
            break
        rec = found.setdefault(c["id"], {"checked": date.today().isoformat(), "pv": PV, "applicant": None, "attorney": None,
                                          "source": None, "doc": None, "owners": []})
        rec["owners_tried"] = ds[0].get("added") or date.today().isoformat()
        for d in ds:
            read2 += 1
            try:
                with tempfile.TemporaryDirectory() as td:
                    path = Path(td) / "f.pdf"
                    m = mirror.get(d["id"])
                    if m and verified.get(d["id"]) == m["asset"]:
                        r = requests.get(f"https://github.com/{DM.REPO}/releases/download/{m.get('tag', 'documents')}/{m['asset']}", timeout=120)
                        r.raise_for_status()
                        path.write_bytes(r.content)
                    else:
                        DM.download(s, d["id"], path)
                        time.sleep(0.6)
                    got = parse(text_of(path), "disclosure")
            except Exception as e:
                print("could not read", c["id"], d.get("name"), e, file=sys.stderr)
                continue
            if got["owners"]:
                rec["owners"], rec["owners_doc"] = got["owners"][:12], d.get("name")
                got_n += 1
                break
    apath.write_text(json.dumps(found))
    print(f"owners: read {read2} disclosures, owners found for {got_n}; {sum(1 for v in found.values() if v.get('owners'))} cases with owners in all")


if __name__ == "__main__":
    main()
