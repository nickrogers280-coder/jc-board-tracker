import re, requests
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
H = "https://cityofjerseycity.civicweb.net"
def items(path):
    x = requests.get(H + path, headers=UA, timeout=60)
    return re.findall(r'data-id="(\d+)" data-parentid="\d+" data-order="\d+" data-type="(\w+)" data-title="([^"]*)"', x.text)
print("ROOT", items("/filepro/documents/"))
y = requests.get(H + "/Portal/MeetingInformation.aspx?Id=385", headers=UA, timeout=60)
t = re.sub(r"\s+", " ", re.sub(r"<script.*?</script>", "", y.text, flags=re.S))
txt = re.sub(r"<[^>]+>", "\n", t); txt = re.sub(r"\n\s*\n+", "\n", txt)
i = txt.find("Ordinance"); print(txt[i-1500:i+4000])
for mid in (5, 50, 100, 150, 200, 250, 300):
    y = requests.get(H + f"/Portal/MeetingInformation.aspx?Id={mid}", headers=UA, timeout=60)
    print(mid, y.status_code, re.findall(r'<span[^>]*id="[^"]*MeetingTitle[^"]*"[^>]*>(.*?)</span>', y.text)[:1], re.findall(r"(Regular|Special|Caucus)[^<]{0,80}20\d\d", y.text)[:1])
