import json, re, collections, requests
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
a = json.load(open("raw/applicants.json"))
print("records", len(a), "with owners", sum(1 for v in a.values() if v.get("owners")))
n = collections.Counter(len(v.get("owners") or []) for v in a.values()); print(sorted(n.items()))
i = 0
for k, v in a.items():
    if v.get("owners"):
        print(k, "|", v.get("applicant"), "|", [(o["name"], o.get("pct")) for o in v["owners"]][:6]); i += 1
        if i > 40: break
own = collections.Counter(o["name"].upper() for v in a.values() for o in v.get("owners") or [])
print("most common owners", own.most_common(40))
for u in ("https://www.njportal.com/DOR/BusinessNameSearch/Search/BusinessName",
          "https://www.njportal.com/DOR/BusinessNameSearch/",
          "https://api.opencorporates.com/v0.4/companies/search?q=417+communipaw+oz&jurisdiction_code=us_nj",
          "https://opencorporates.com/companies?q=417+communipaw+oz&jurisdiction_code=us_nj"):
    try:
        r = requests.get(u, headers=UA, timeout=40); print("##", u, r.status_code, r.headers.get("content-type"), len(r.text)); print(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))[:1200])
    except Exception as e: print("##", u, "ERR", e)
try:
    s = requests.Session(); s.headers.update(UA)
    g = s.get("https://www.njportal.com/DOR/BusinessNameSearch/", timeout=40)
    tok = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', g.text)
    forms = re.findall(r'<form[^>]*>', g.text); inputs = re.findall(r'<input[^>]*name="([^"]+)"', g.text)
    print("forms", forms, "inputs", inputs, "token", bool(tok))
    if tok:
        r = s.post("https://www.njportal.com/DOR/BusinessNameSearch/Search/BusinessName", data={"__RequestVerificationToken": tok.group(1), "BusinessName": "417 Communipaw OZ", "StartsWith": "false"}, timeout=40)
        print("POST", r.status_code, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))[:2500])
except Exception as e: print("njportal ERR", e)
