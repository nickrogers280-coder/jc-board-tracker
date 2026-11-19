import re, requests, html as H_
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
H = "https://cityofjerseycity.civicweb.net"
y = requests.get(H + "/Portal/MeetingTypeList.aspx", headers=UA, timeout=60)
t = re.sub(r"\s+", " ", y.text)
for m in re.finditer(r'href="(/Portal/MeetingInformation\.aspx\?[^"]+)"[^>]*>(.{0,200}?)</a>', t): print("  ", m.group(1), re.sub("<[^>]+>", " ", m.group(2))[:120])
for ty in (10, 16):
    y = requests.get(H + f"/Portal/MeetingInformation.aspx?type={ty}", headers=UA, timeout=60)
    t = re.sub(r"\s+", " ", y.text)
    print("## type", ty, y.url, len(t))
    print("  title:", re.findall(r"<title>(.*?)</title>", t)[:1])
    ids = re.findall(r"MeetingInformation\.aspx\?Id=(\d+)", t); print("  meeting ids", len(set(ids)), ids[:20])
    docs = sorted(set(re.findall(r'(/document/\d+[^"\']*)', t))); print("  docs", docs[:20])
    i = t.find("Agenda"); print("  ctx", re.sub("<[^>]+>", " | ", t[i-300:i+1500])[:1500])
