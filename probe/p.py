import math, requests, json
PARCELS = "https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/Parcels_Composite_NJ_WM/FeatureServer/0/query"
F = "PAMS_PIN,PROP_LOC,PCLBLOCK,PCLLOT,CALC_ACRE,LAND_DESC,PROP_CLASS,ST_ADDRESS,CITY_STATE,LAND_VAL,IMPRVT_VAL,ADD_LOTS1"
def q(where):
    r = requests.post(PARCELS, data={"where": where, "outFields": F, "returnGeometry": "true", "outSR": "4326", "f": "json"}, timeout=90)
    return r.json().get("features", [])
def acres(f):
    tot = 0
    for ring in (f.get("geometry") or {}).get("rings", []):
        lat0 = math.radians(sum(y for _, y in ring) / len(ring))
        xy = [(x * 111320 * math.cos(lat0), y * 110574) for x, y in ring]
        tot += sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(xy, xy[1:])) / 2
    return abs(tot) / 4046.86
def show(tag, fs):
    t = 0
    for f in sorted(fs, key=lambda f: f["attributes"]["PAMS_PIN"]):
        a = f["attributes"]; ac = acres(f); t += ac
        print(tag, a["PAMS_PIN"], "|", a.get("PROP_LOC"), "|", round(ac, 3), "ac | tax", a.get("CALC_ACRE"), "|", a.get("LAND_DESC"), "| cls", a.get("PROP_CLASS"), "| bill to:", a.get("ST_ADDRESS"), a.get("CITY_STATE"), "| add lots:", a.get("ADD_LOTS1"))
    print(tag, "TOTAL", round(t, 2), "acres,", len(fs), "lots")
lease = ["6001_1", "6001_9", "6001_13", "6001_33", "6901_15", "6901_16", "6901_17", "6901_18", "6901_19", "6901_20", "5903_21", "6901_18.01", "6001_5"]
show("LEASE", q("PAMS_PIN IN (" + ",".join(f"'0906_{p}'" for p in lease) + ")"))
show("BELGROVE", q("PAMS_PIN LIKE '0906_%' AND (UPPER(ST_ADDRESS) LIKE '%BELGROVE%' OR UPPER(ST_ADDRESS) LIKE '%ALARIS%')"))
show("BLOCKS", q("PAMS_PIN LIKE '0906_6901_%' OR PAMS_PIN LIKE '0906_6001_%' OR PAMS_PIN LIKE '0906_5903_21%'"))
