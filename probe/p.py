import json, re, sys, requests
sys.path.insert(0, ".")
import fetch
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
cache = json.load(open("raw/agenda_text_cache.json"))
ag, _ = fetch.parse_agendas(cache)
cs = json.load(open("data/map.json"))["cases"]
arc = [c for c in cs if c.get("archived") and c["status"] == "Archived"]
got = [(c["id"], ag.get(c["id"], {}).get("memo"), ag.get(c["id"], {}).get("last", "")[:50]) for c in arc]
print("memo found for", sum(1 for g in got if g[1]), "of", len(arc))
for g in got: print("  ", g)
for cn in ("P20-012", "P22-156", "Z21-050", "P20-177", "Z22-063"):
    print(cn, {k: ag.get(cn, {}).get(k) for k in ("addr", "app", "bl")})
def show(u, n=3000, **kw):
    try:
        r = requests.get(u, headers=UA, timeout=60, **kw); print("##", u, r.status_code, r.headers.get("content-type")); return r
    except Exception as e:
        print("##", u, "ERR", e)
r = show("https://thejcra.org/wp-json/wp/v2/media", params={"mime_type": "application/pdf", "per_page": 100, "_fields": "id,date,source_url,title"})
if r is not None and r.ok:
    print("total", r.headers.get("X-WP-Total"), "pages", r.headers.get("X-WP-TotalPages"))
    for m in r.json()[:40]: print("  ", m["date"][:10], m["source_url"])
for u in ("https://www.jerseycitynj.gov/cityhall/Clerk/ordinances___resolutions__2019-_present_",
          "https://www.jerseycitynj.gov/cityhall/Clerk/view_agenda_and_request_to_speak",
          "https://jerseycitynj.legistar.com/Legislation.aspx",
          "https://webapi.legistar.com/v1/jerseycitynj/matters?$top=3",
          "https://webapi.legistar.com/v1/jerseycity/matters?$top=3"):
    r = show(u)
    if r is not None and r.ok:
        links = sorted(set(re.findall(r'href="([^"]+)"', r.text)))
        print("  links", len(links))
        for l in links:
            if re.search(r"pdf|Resolution|Ordinance|Agenda|20(19|2\d)", l, re.I): print("   ", l)
        if "legistar" in u: print(r.text[:800])
