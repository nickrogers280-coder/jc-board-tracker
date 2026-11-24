import requests, os
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
os.makedirs("out", exist_ok=True)
for name, u in [("city-v-hrh-verified-complaint.pdf", "https://betterblocksnj.org/wp-content/uploads/2026/03/christ-hospital-complain.pdf"),
                ("city-v-hrh-injunction-denied.pdf", "https://betterblocksnj.org/wp-content/uploads/2026/03/christ-hospital-injunction-denied.pdf"),
                ("hrh-letter-to-jc-planning-2025-10-13.pdf", "https://hudsoncountyview.com/wp-content/uploads/2025/10/HRH-to-JC-planning-10-13-25.pdf")]:
    r = requests.get(u, headers=UA, timeout=90)
    print("GOT", name, r.status_code, r.headers.get("content-type"), len(r.content))
    if r.ok and r.content[:4] == b"%PDF":
        open("out/" + name, "wb").write(r.content)
