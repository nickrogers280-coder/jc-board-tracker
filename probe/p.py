import requests, io, pdfplumber
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
for u in """https://thejcra.org/wp-content/uploads/2026/09/DOC091526.pdf
https://thejcra.org/wp-content/uploads/2024/10/SP-October-2024-Agenda-Final.pdf
https://thejcra.org/wp-content/uploads/2022/09/Agenda-September-20-2022.pdf
https://thejcra.org/wp-content/uploads/2021/06/agenda-001.pdf
https://thejcra.org/wp-content/uploads/2020/05/May-2020-Agenda.pdf
https://thejcra.org/wp-content/uploads/2019/11/agenda-nov-001-1.pdf""".split():
    r = requests.get(u, headers=UA, timeout=120)
    with pdfplumber.open(io.BytesIO(r.content)) as p:
        t = "\n".join((pg.extract_text() or "") for pg in p.pages[:6]); n = len(p.pages)
    print("#####", u, n, "pages", len(t), "chars"); print(t[:2200])
