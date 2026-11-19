import re, requests, html
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
H = "https://cityofjerseycity.civicweb.net"
r = requests.get(H + "/document/81771/", headers=UA, timeout=120)
t = r.text
links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', t, re.S)
print("links", len(links)); [print("  ", l[0][:120], "|", re.sub("<[^>]+>|\s+", " ", l[1])[:80]) for l in links[:25]]
x = re.sub(r"<(script|style).*?</\1>", "", t, flags=re.S)
x = re.sub(r"<br\s*/?>|</p>|</div>|</tr>|</li>|</h\d>", "\n", x)
x = html.unescape(re.sub(r"<[^>]+>", " ", x)); x = re.sub(r"[ \t\xa0]+", " ", x); x = re.sub(r"\n\s*\n+", "\n", x)
i = x.lower().find("redevelop")
print(x[:2500]); print("=========="); print(x[i-3000:i+3000])
