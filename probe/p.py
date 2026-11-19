import re, requests, io, pdfplumber
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
H = "https://cityofjerseycity.civicweb.net"
def items(fid):
    x = requests.get(H + f"/filepro/documents/{fid}/", headers=UA, timeout=60)
    return re.findall(r'data-id="(\d+)" data-parentid="\d+" data-order="\d+" data-type="(\w+)" data-title="([^"]*)"', x.text)
top = items(1021); print("COUNCIL", top)
for y in top[:12]:
    s = items(y[0]) if y[1] == "folder" else []
    print("  ", y, len(s), s[:6])
y = next(i for i in top if "2022" in i[2])
s = items(y[0]); f = s[0]; s2 = items(f[0]) if f[1] == "folder" else [f]; print("SUB", f, s2[:10])
d = next(i for i in s2 if i[1] == "document")
r = requests.get(H + f"/document/{d[0]}/", headers=UA, timeout=120)
print("DOC", d, r.status_code, r.headers.get("content-type"), len(r.content))
if "pdf" in (r.headers.get("content-type") or ""):
    with pdfplumber.open(io.BytesIO(r.content)) as p:
        print("pages", len(p.pages)); t = "\n".join((pg.extract_text() or "") for pg in p.pages[:12])
    i = t.find("ORDINANCE"); print(t[:1500]); print("....."); print(t[i:i+5000])
else:
    print(r.text[:1500])
