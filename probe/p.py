import re, requests
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
P = "https://www.jerseycitynj.gov/cityhall/Clerk/ordinances___resolutions__2019-_present_"
r = requests.get(P, headers=UA, timeout=60)
print("final url", r.url)
top = re.findall(r'data-id="(\d+)" data-parentid="(\d+)" data-order="\d+" data-type="(\w+)" data-title="([^"]*)"', r.text)
print(len(top), top[:8])
for m in re.finditer(r'(iframe|base)[^>]+>', r.text): print(m.group(0)[:300])
print(re.findall(r'https?://[a-z0-9.-]*civicweb[a-z0-9./-]*', r.text)[:10])
fid = top[0][0]
for host in ("https://www.jerseycitynj.gov", "https://jerseycitynj.civicweb.net", "https://jerseycity.civicweb.net", "https://jerseycity.hosted.civiclive.com"):
    for path in (f"/filepro/documents/{fid}", f"/filepro/documents/{fid}/", f"/document/{fid}"):
        try:
            x = requests.get(host + path, headers=UA, timeout=40)
            sub = re.findall(r'data-id="(\d+)" data-parentid="\d+" data-order="\d+" data-type="(\w+)" data-title="([^"]*)"', x.text)
            print(host + path, x.status_code, len(x.text), x.url, sub[:12])
        except Exception as e:
            print(host + path, "ERR", e)
