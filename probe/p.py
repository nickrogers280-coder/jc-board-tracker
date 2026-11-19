import json, re, sys, io, requests, pdfplumber
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
for u in ("https://www.jerseycitynj.gov/cityhall/Clerk/ordinances___resolutions__2019-_present_",
          "https://www.jerseycitynj.gov/cityhall/Clerk/view_agenda_and_request_to_speak"):
    r = requests.get(u, headers=UA, timeout=60)
    print("##", u, len(r.text))
    for l in sorted(set(re.findall(r'(?:href|src)="([^"]+)"', r.text))): print("   ", l)
    i = r.text.lower().find("resolution"); print(re.sub(r"\s+", " ", r.text[i-500:i+3000]))
def pdf(u, n=6000):
    r = requests.get(u, headers=UA, timeout=120)
    with pdfplumber.open(io.BytesIO(r.content)) as p:
        t = "\n".join((pg.extract_text() or "") for pg in p.pages[:25])
    print("##PDF", u, len(r.content), "pages", "\n", t[:n])
pdf("https://thejcra.org/wp-content/uploads/2026/10/use-this-October-2026-Resolution-Packet-1.pdf", 7000)
pdf("https://thejcra.org/wp-content/uploads/2026/10/JCRA-October-2026-Agenda.pdf", 5000)
