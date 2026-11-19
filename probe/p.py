import re, requests, html
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
B = "https://www.jerseycitynj.gov"
def items(u):
    r = requests.get(u, headers=UA, timeout=60)
    out = re.findall(r'data-id="(\d+)" data-parentid="(\d+)" data-order="\d+" data-type="(\w+)" data-title="([^"]*)"', r.text)
    print("##", u, r.status_code, len(r.text), len(out))
    return r, out
r, top = items(B + "/filepro/documents/108")
for x in top[:60]: print("  ", x)
# first meeting folder
fid = next(x[0] for x in top if x[2] == "folder")
r, sub = items(B + f"/filepro/documents/{fid}")
for x in sub[:80]: print("  ", x)
links = sorted(set(re.findall(r'href="(/document/[^"]+|/filepro/document/[^"]+|[^"]*\.pdf[^"]*)"', r.text)))
print("doc links", links[:20])
if sub:
    for x in sub:
        if x[2] != "folder":
            for u in (f"/document/{x[0]}", f"/filepro/document/{x[0]}", f"/document/{x[0]}/"):
                rr = requests.get(B + u, headers=UA, timeout=60, allow_redirects=True)
                print("try", u, rr.status_code, rr.headers.get("content-type"), len(rr.content), rr.url)
            break
    sf = [x for x in sub if x[2] == "folder"]
    if sf:
        r, sub2 = items(B + f"/filepro/documents/{sf[0][0]}")
        for x in sub2[:40]: print("   ", x)
