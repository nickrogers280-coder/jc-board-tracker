import re, requests
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
H = "https://cityofjerseycity.civicweb.net"
def items(path):
    x = requests.get(H + path, headers=UA, timeout=60)
    sub = re.findall(r'data-id="(\d+)" data-parentid="\d+" data-order="\d+" data-type="(\w+)" data-title="([^"]*)"', x.text)
    print("##", path, x.status_code, len(sub)); return x, sub
x, s = items("/filepro/documents/441858/")
for i in s[:15]: print("  ", i)
f = next((i for i in s if i[1] == "folder"), None)
if f:
    x, s2 = items(f"/filepro/documents/{f[0]}/")
    for i in s2[:25]: print("    ", i)
    d = next((i for i in s2 if i[1] == "document"), None)
    if d:
        for p in (f"/document/{d[0]}/", f"/filepro/document/{d[0]}/"):
            y = requests.get(H + p, headers=UA, timeout=60); print("doc", p, y.status_code, y.headers.get("content-type"), len(y.content), y.text[:300] if "html" in (y.headers.get("content-type") or "") else "")
for p in ("/Portal/MeetingTypeList.aspx", "/Portal/", "/Portal/MeetingSchedule.aspx"):
    y = requests.get(H + p, headers=UA, timeout=60)
    print("##", p, y.status_code, y.url, len(y.text))
    for l in sorted(set(re.findall(r'href="([^"]+)"', y.text)))[:60]:
        if re.search(r"Meeting|Agenda|document", l, re.I): print("   ", l)
