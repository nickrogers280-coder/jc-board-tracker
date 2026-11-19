import json, random, sys, collections
sys.path.insert(0, ".")
import civic
civic.main()
db = civic.load()
it = db["items"]
print("by src/kind", collections.Counter((v["src"], v["kind"]) for v in it.values()))
print("jcra agendas with 0 items", sum(1 for v in db["jcra_seen"].values() if not v), "of", len(db["jcra_seen"]))
for u, v in list(db["jcra_seen"].items())[:200]:
    if not v: print("   empty:", u)
random.seed(1)
for k in random.sample(list(it), 12): print("SAMPLE", it[k]["src"], it[k]["kind"], it[k]["date"], it[k]["title"][:230])
cases = json.load(open("data/map.json"))["cases"]
m = civic.match_cases(cases, db)
for cid in ("P2025-0177", "P22-146", "P2023-0042"):
    for i in m.get(cid, []): print("417", cid, it[i]["src"], it[i]["date"], it[i].get("label"), it[i]["title"][:200])
for cid in random.sample(list(m), 10):
    i = m[cid][0]; c = next(c for c in cases if c["id"] == cid)
    print("MATCH", cid, c["address"][:40], "|", (c.get("applicant") or "")[:30], "|", it[i]["src"], it[i]["title"][:160])
