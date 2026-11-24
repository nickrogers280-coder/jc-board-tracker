import requests, json
pins = ["0906_6901_15","0906_6901_16","0906_6901_17","0906_6901_18.01","0906_5903_21","0906_6001_2","0906_6001_3","0906_6001_4","0906_6001_5","0906_6001_6","0906_6001_7","0906_6001_8","0906_6001_9","0906_6001_13"]
r = requests.post("https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/Parcels_Composite_NJ_WM/FeatureServer/0/query",
    data={"where": "PAMS_PIN IN (" + ",".join(f"'{p}'" for p in pins) + ")", "outFields": "PAMS_PIN,CALC_ACRE,PROP_LOC,LAND_DESC,PROP_CLASS,LAND_VAL,IMPRVT_VAL", "returnGeometry": "true", "outSR": "3424", "f": "json"}, timeout=90)
tot = 0
for f in r.json().get("features", []):
    a = f["attributes"]
    # planar area in sq ft (NJ State Plane ft) from rings, shoelace
    area = 0
    for ring in (f.get("geometry") or {}).get("rings", []):
        s = 0
        for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
            s += x1 * y2 - x2 * y1
        area += s / 2
    area = abs(area)
    tot += area
    print("ROW", a["PAMS_PIN"], a.get("PROP_LOC"), "calc_acre", a.get("CALC_ACRE"), "geom_acres", round(area / 43560, 3), a.get("LAND_DESC"), a.get("PROP_CLASS"), a.get("LAND_VAL"), a.get("IMPRVT_VAL"))
print("ROW TOTAL geom acres", round(tot / 43560, 2), "sqft", round(tot))
