import sys, requests
sys.path.insert(0, ".")
import civic
S = civic._session()
for u in ("https://thejcra.org/wp-content/uploads/2022/09/Agenda-September-20-2022.pdf",
          "https://thejcra.org/wp-content/uploads/2019/11/agenda-nov-001-1.pdf",
          "https://thejcra.org/wp-content/uploads/2021/06/agenda-001.pdf"):
    t = civic._pdf_text(S.get(u, timeout=120).content)
    print("#####", u, len(t), civic._meeting_date(t, None))
    items = civic.jcra_items(t)
    print("items", len(items))
    for k, b in items[:12]: print("  ", k, b[:220])
    if not items: print(t[:3000])
