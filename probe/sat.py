"""Satellite image of the 176 Palisade Avenue study area with every lot outlined (Esri World Imagery + NJ parcels)."""
import io, math, requests
from PIL import Image, ImageDraw, ImageFont

PARCELS = "https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/Parcels_Composite_NJ_WM/FeatureServer/0/query"
TILE = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
UA = {"User-Agent": "JC Board Tracker (research)"}
CONDEMN = ["6901_15", "6901_16", "6901_17", "6901_18.01", "5903_21", "6001_3", "6001_4", "6001_5", "6001_7", "6001_8", "6001_9", "6001_13"]
NONCOND = ["6001_2", "6001_6"]
APPONLY = ["6901_3", "6901_4", "6001_33", "5803_19", "5803_20", "5803_21", "5803_22", "5803_23"]
ALL = CONDEMN + NONCOND + APPONLY
r = requests.post(PARCELS, data={"where": "PAMS_PIN IN (" + ",".join(f"'0906_{p}'" for p in ALL) + ")",
    "outFields": "PAMS_PIN,PROP_LOC,PCLBLOCK,PCLLOT", "returnGeometry": "true", "outSR": "4326", "f": "json"}, timeout=90)
feats = {f["attributes"]["PAMS_PIN"][5:]: f for f in r.json()["features"]}
print("parcels found", len(feats), "missing", [p for p in ALL if p not in feats])

def acres(f):
    tot = 0
    for ring in f["geometry"]["rings"]:
        lat0 = math.radians(sum(y for _, y in ring) / len(ring))
        xy = [(x * 111320 * math.cos(lat0), y * 110574) for x, y in ring]
        a = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(xy, xy[1:])) / 2
        tot += a  # rings: outer clockwise, holes counter-clockwise in Esri JSON
    return abs(tot) / 4046.86
ACRE = {p: acres(f) for p, f in feats.items()}

Z = 19
def px(lon, lat):
    n = 2 ** Z * 256
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y
pts = [px(x, y) for f in feats.values() for ring in f["geometry"]["rings"] for x, y in ring]
minx, maxx = min(p[0] for p in pts), max(p[0] for p in pts)
miny, maxy = min(p[1] for p in pts), max(p[1] for p in pts)
pad = 140
minx, maxx, miny, maxy = minx - pad, maxx + pad, miny - pad - 90, maxy + pad
tx0, tx1, ty0, ty1 = int(minx // 256), int(maxx // 256), int(miny // 256), int(maxy // 256)
canvas = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
for tx in range(tx0, tx1 + 1):
    for ty in range(ty0, ty1 + 1):
        t = requests.get(TILE.format(z=Z, x=tx, y=ty), headers=UA, timeout=60)
        canvas.paste(Image.open(io.BytesIO(t.content)).convert("RGB"), ((tx - tx0) * 256, (ty - ty0) * 256))
ox, oy = tx0 * 256, ty0 * 256
canvas = canvas.crop((int(minx - ox), int(miny - oy), int(maxx - ox), int(maxy - oy)))
ox, oy = minx, miny
over = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
d = ImageDraw.Draw(over)
try:
    F = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 17)
    FS = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
    FT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
except Exception:
    F = FS = FT = ImageFont.load_default()
STY = {"c": ((230, 57, 70, 70), (230, 57, 70, 255)), "n": ((255, 209, 102, 80), (255, 209, 102, 255)), "a": ((76, 201, 240, 55), (76, 201, 240, 255))}
def kind(p): return "c" if p in CONDEMN else "n" if p in NONCOND else "a"
labels = []
for p, f in feats.items():
    k = kind(p)
    for ring in f["geometry"]["rings"]:
        xy = [(px(x, y)[0] - ox, px(x, y)[1] - oy) for x, y in ring]
        d.polygon(xy, fill=STY[k][0])
        d.line(xy + [xy[0]], fill=STY[k][1], width=4 if k != "a" else 3)
    ring = max(f["geometry"]["rings"], key=len)
    cx = sum(px(x, y)[0] for x, y in ring) / len(ring) - ox
    cy = sum(px(x, y)[1] for x, y in ring) / len(ring) - oy
    a = f["attributes"]
    labels.append((cx, cy, f"{a['PCLBLOCK']}/{a['PCLLOT']}", k))
canvas = Image.alpha_composite(canvas.convert("RGBA"), over)
d = ImageDraw.Draw(canvas)
for cx, cy, t, k in labels:
    w = d.textlength(t, font=FS)
    d.rounded_rectangle((cx - w / 2 - 4, cy - 10, cx + w / 2 + 4, cy + 10), 4, fill=(0, 0, 0, 170))
    d.text((cx - w / 2, cy - 9), t, font=FS, fill=(255, 255, 255))
W, H = canvas.size
d.rectangle((0, 0, W, 78), fill=(0, 0, 0, 185))
d.text((18, 10), "176 Palisade Avenue Study Area (former Christ Hospital), Jersey City", font=FT, fill=(255, 255, 255))
d.text((18, 46), "Council Res. 26-130 · Planning Board case P2026-0156 · labels are Block/Lot", font=FS, fill=(220, 220, 220))
leg = [("c", "Study area, condemnation proposed (12 lots)"), ("n", "Study area, no condemnation (6001/2, 6001/6)"), ("a", "Also in 176 Palisades Holdings' 2,233-unit application (P2025-0268)")]
lw = max(d.textlength(t, font=F) for _, t in leg) + 60
y0 = H - 22 - 30 * len(leg)
d.rounded_rectangle((14, y0 - 12, 14 + lw, H - 14), 8, fill=(0, 0, 0, 190))
for i, (k, t) in enumerate(leg):
    y = y0 + i * 30
    d.rectangle((26, y + 2, 48, y + 20), fill=STY[k][0], outline=STY[k][1], width=3)
    d.text((58, y), t, font=F, fill=(255, 255, 255))
# Acreage breakdown, bottom right
FB = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15)
FR = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
def addr(p):
    a = (feats[p]["attributes"].get("PROP_LOC") or "").title().replace("Ave.", "Ave").replace("Avenue", "Ave")
    return a or "Palisade Ave (no number)"
groups = [("c", "Condemnation proposed", CONDEMN), ("n", "No condemnation", NONCOND), ("a", "Application only (not in study)", APPONLY)]
rows = []
for k, title, pins in groups:
    rows.append(("H", k, title, "", ""))
    sub = 0
    for p in sorted(pins, key=lambda q: -ACRE.get(q, 0)):
        if p in feats:
            rows.append(("R", k, p.replace("_", "/"), addr(p), f"{ACRE[p]:.2f}"))
            sub += ACRE[p]
    rows.append(("S", k, "Subtotal", "", f"{sub:.2f}"))
study = sum(ACRE[p] for p in CONDEMN + NONCOND if p in feats)
allac = sum(ACRE.values())
rows.append(("T", "", "Study area total (14 lots)", "", f"{study:.2f}"))
rows.append(("T", "", "Study area + application lots (22)", "", f"{allac:.2f}"))
c1, c2, c3 = 92, 300, 70
lh = 22
tw = c1 + c2 + c3 + 36
th = 46 + lh * len(rows) + 6 * sum(1 for r_ in rows if r_[0] == "S") + 4 * sum(1 for r_ in rows if r_[0] == "T") + 22
x0, y0b = W - tw - 16, H - th - 40
d.rounded_rectangle((x0, y0b, x0 + tw, y0b + th), 8, fill=(0, 0, 0, 200))
d.text((x0 + 14, y0b + 10), "Lot acreage (from NJ parcel map)", font=F, fill=(255, 255, 255))
y = y0b + 42
for kind_, k, a, b, c in rows:
    if kind_ == "H":
        d.rectangle((x0 + 14, y + 4, x0 + 28, y + 18), fill=STY[k][0], outline=STY[k][1], width=2)
        d.text((x0 + 36, y), a, font=FB, fill=(255, 255, 255))
    elif kind_ == "R":
        d.text((x0 + 22, y), a, font=FR, fill=(235, 235, 235))
        d.text((x0 + 22 + c1, y), b[:34], font=FR, fill=(235, 235, 235))
        d.text((x0 + tw - 14 - d.textlength(c, font=FR), y), c, font=FR, fill=(235, 235, 235))
    elif kind_ == "S":
        d.line((x0 + 22, y + 1, x0 + tw - 14, y + 1), fill=(150, 150, 150), width=1)
        d.text((x0 + 22 + c1, y + 2), a, font=FB, fill=(255, 255, 255))
        d.text((x0 + tw - 14 - d.textlength(c, font=FB), y + 2), c, font=FB, fill=(255, 255, 255))
        y += 6
    else:
        d.line((x0 + 14, y, x0 + tw - 14, y), fill=(255, 255, 255), width=1)
        d.text((x0 + 22, y + 3), a, font=FB, fill=(255, 224, 102))
        d.text((x0 + tw - 14 - d.textlength(c, font=FB), y + 3), c, font=FB, fill=(255, 224, 102))
        y += 4
    y += lh
d.text((x0, H - 30), "Imagery: Esri World Imagery · Parcels: NJOGIS · acres computed from parcel outlines", font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12), fill=(235, 235, 235))
print("ACRES", {k: round(v, 3) for k, v in ACRE.items()}, "study", round(study, 2), "all", round(allac, 2))
import os
os.makedirs("out", exist_ok=True)
canvas.convert("RGB").save("out/176-palisade-study-area-satellite-acreage.jpg", quality=88)
print("image", canvas.size)
