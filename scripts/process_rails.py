#!/usr/bin/env python3
"""Process OSM railway extracts into simplified GeoJSON for railview."""
from __future__ import annotations
import json, math, re, gzip
from decimal import Decimal
from pathlib import Path
import ijson
from shapely.geometry import LineString
from shapely import simplify as shapely_simplify

HSR_OSMIUM = Path("/tmp/rail-data/hsr_osmium.geojson")
RAILS_OSMIUM = Path("/tmp/rail-data/rails_all_osmium.geojson")
HDX = Path("/tmp/rail-data/railways.geojson")
OUT_DIR = Path("/workspace/railview/public/data")
OUT_DIR.mkdir(parents=True, exist_ok=True)

HSR_NAME_RE = re.compile(
    r"(高速|高铁|客运专线|客运线|城际|intercity|high.?speed|\bHSR\b)",
    re.I,
)

def num(x):
    if isinstance(x, Decimal):
        return float(x)
    if isinstance(x, (list, tuple)):
        return [num(i) for i in x]
    return x

def douglas_keep(coords, tol_deg: float):
    coords = [[float(a), float(b)] for a, b in coords]
    if len(coords) <= 2:
        return coords
    try:
        ls = LineString(coords)
        if ls.is_empty or ls.length == 0:
            return coords
        simp = shapely_simplify(ls, tol_deg, preserve_topology=False)
        if simp.is_empty or simp.geom_type != "LineString":
            return coords
        out = [list(c) for c in simp.coords]
        return out if len(out) >= 2 else coords
    except Exception:
        return coords

def round_coords(coords, nd=5):
    return [[round(float(x), nd), round(float(y), nd)] for x, y in coords]

def props_name(props):
    if not props:
        return None
    for k in ("name", "name:zh", "name_zh", "name:en", "name_en"):
        v = props.get(k)
        if v:
            return str(v)
    return None

def iter_line_features(path: Path):
    with open(path, "rb") as f:
        for feat in ijson.items(f, "features.item"):
            geom = feat.get("geometry") or {}
            if geom.get("type") not in ("LineString", "MultiLineString"):
                continue
            yield feat

def process_osmium_hsr():
    if not HSR_OSMIUM.exists():
        return []
    feats = []
    for feat in iter_line_features(HSR_OSMIUM):
        props = feat.get("properties") or {}
        # skip service tracks
        svc = str(props.get("service") or "").lower()
        if svc in ("yard", "siding", "spur", "crossover"):
            continue
        if str(props.get("railway") or "") not in ("rail", "yes", ""):
            # keep if highspeed tagged even if railway missing on export
            if str(props.get("highspeed") or "") != "yes":
                continue
        geom = feat["geometry"]
        if geom["type"] == "LineString":
            lines = [geom["coordinates"]]
        else:
            lines = geom["coordinates"]
        name = props_name(props)
        for coords in lines:
            if len(coords) < 2:
                continue
            simp = round_coords(douglas_keep(num(coords), 0.003))
            feats.append({
                "type": "Feature",
                "properties": {
                    "id": props.get("@id") or props.get("id"),
                    "name": name,
                    "kind": "hsr",
                    "source": "osmium",
                },
                "geometry": {"type": "LineString", "coordinates": simp},
            })
    print(f"osmium HSR lines: {len(feats)}")
    return feats

def process_osmium_conventional(hsr_ids: set):
    """All railway=rail minus highspeed=yes and service tracks."""
    if not RAILS_OSMIUM.exists():
        return None
    feats = []
    n = 0
    for feat in iter_line_features(RAILS_OSMIUM):
        props = feat.get("properties") or {}
        if str(props.get("highspeed") or "").lower() == "yes":
            continue
        svc = str(props.get("service") or "").lower()
        if svc in ("yard", "siding", "spur", "crossover"):
            continue
        if str(props.get("railway") or "") != "rail":
            continue
        usage = str(props.get("usage") or "").lower()
        # optional: skip tourism/military? keep industrial for density look
        geom = feat["geometry"]
        if geom["type"] == "LineString":
            lines = [geom["coordinates"]]
        else:
            lines = geom["coordinates"]
        name = props_name(props)
        for coords in lines:
            if len(coords) < 2:
                continue
            n += 1
            # stronger simplify for conventional overview
            simp = round_coords(douglas_keep(num(coords), 0.012))
            feats.append({
                "type": "Feature",
                "properties": {
                    "id": props.get("@id") or props.get("id"),
                    "name": name,
                    "kind": "conventional",
                    "source": "osmium",
                },
                "geometry": {"type": "LineString", "coordinates": simp},
            })
            if n % 50000 == 0:
                print(f"  conv processed {n}")
    print(f"osmium conventional raw: {len(feats)}")
    return feats

def process_hdx_fallback():
    conv, hsr_h, stations = [], [], []
    n_line = 0
    with open(HDX, "rb") as f:
        for feat in ijson.items(f, "features.item"):
            props = feat.get("properties") or {}
            geom = feat.get("geometry") or {}
            gtype = geom.get("type")
            railway = props.get("railway")
            name = props.get("name") or props.get("name_zh") or ""
            if isinstance(name, Decimal):
                name = str(name)
            if railway == "station" and gtype == "Point" and name:
                coords = num(geom.get("coordinates"))
                if coords and len(coords) >= 2:
                    stations.append({
                        "type": "Feature",
                        "properties": {"id": props.get("id"), "name": str(name), "kind": "station"},
                        "geometry": {"type": "Point", "coordinates": [round(coords[0], 5), round(coords[1], 5)]},
                    })
                continue
            if railway != "rail" or gtype != "LineString":
                continue
            coords = num(geom.get("coordinates") or [])
            if len(coords) < 2:
                continue
            n_line += 1
            simp = round_coords(douglas_keep(coords, 0.012))
            is_hsr = bool(name and HSR_NAME_RE.search(str(name)))
            out = {
                "type": "Feature",
                "properties": {
                    "id": props.get("id"),
                    "name": str(name) if name else None,
                    "kind": "hsr" if is_hsr else "conventional",
                },
                "geometry": {"type": "LineString", "coordinates": simp},
            }
            (hsr_h if is_hsr else conv).append(out)
            if n_line % 50000 == 0:
                print(f"  HDX lines {n_line}")
    print(f"HDX fallback: lines={n_line} conv={len(conv)} hsr={len(hsr_h)} sta={len(stations)}")
    return conv, hsr_h, stations

def process_hdx_stations_only():
    stations = []
    with open(HDX, "rb") as f:
        for feat in ijson.items(f, "features.item"):
            props = feat.get("properties") or {}
            geom = feat.get("geometry") or {}
            if props.get("railway") != "station" or geom.get("type") != "Point":
                continue
            name = props.get("name") or props.get("name_zh")
            if not name:
                continue
            coords = num(geom.get("coordinates"))
            if not coords or len(coords) < 2:
                continue
            stations.append({
                "type": "Feature",
                "properties": {"id": props.get("id"), "name": str(name), "kind": "station"},
                "geometry": {"type": "Point", "coordinates": [round(coords[0], 5), round(coords[1], 5)]},
            })
    return stations

def thin_features(feats, max_n=60000, prefer_named=True):
    if len(feats) <= max_n:
        return feats
    named = [f for f in feats if f["properties"].get("name")]
    unnamed = [f for f in feats if not f["properties"].get("name")]
    # keep all named if reasonable, else sample named too
    if prefer_named and len(named) <= max_n:
        budget = max_n - len(named)
        step = max(1, len(unnamed) // max(1, budget))
        return named + unnamed[::step][:budget]
    step = max(1, len(feats) // max_n)
    return feats[::step][:max_n]

def sample_stations(stations, max_n=350):
    scored = []
    for s in stations:
        name = s["properties"]["name"]
        score = 0
        if name.endswith("站"):
            score += 2
        if any(x in name for x in ("北", "南", "东", "西", "虹桥", "西九龙", "南站", "北站")):
            score += 3
        if len(name) >= 3:
            score += 1
        if any(x in name for x in ("高铁", "高速", "火车站")):
            score += 2
        scored.append((score, name, s))
    scored.sort(key=lambda x: (-x[0], x[1]))
    seen, out = set(), []
    for score, name, s in scored:
        if name in seen:
            continue
        seen.add(name)
        out.append(s)
        if len(out) >= max_n:
            break
    return out

def write_fc(path: Path, features, meta=None):
    fc = {"type": "FeatureCollection", "features": features}
    if meta:
        fc["meta"] = meta
    text = json.dumps(fc, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text)
    print(f"wrote {path.name} feats={len(features)} bytes={path.stat().st_size/1e6:.2f}MB")

def main():
    hsr = process_osmium_hsr()
    conv = process_osmium_conventional(set())
    stations = []
    if HDX.exists():
        stations = process_hdx_stations_only()
        print(f"stations from HDX: {len(stations)}")

    if not hsr or conv is None:
        print("Falling back partly/fully to HDX…")
        c2, h2, s2 = process_hdx_fallback()
        if not hsr:
            hsr = h2
        if conv is None:
            conv = c2
        if not stations:
            stations = s2

    conv = thin_features(conv, max_n=55000)
    # If still huge file, dissolve-like further simplify already done; optionally drop short segs
    def length_proxy(f):
        c = f["geometry"]["coordinates"]
        return abs(c[-1][0]-c[0][0]) + abs(c[-1][1]-c[0][1])
    # drop tiny stubs under ~0.02 deg unless named
    conv = [f for f in conv if f["properties"].get("name") or length_proxy(f) >= 0.015]
    print(f"conv after stub filter: {len(conv)}")

    st = sample_stations(stations, 320)
    write_fc(OUT_DIR / "rails-hsr.geojson", hsr, {"source": "Geofabrik China PBF via osmium (highspeed=yes)", "kind": "hsr"})
    write_fc(OUT_DIR / "rails-conventional.geojson", conv, {"source": "Geofabrik/HDX OSM railway=rail", "kind": "conventional"})
    write_fc(OUT_DIR / "stations.geojson", st, {"source": "HOT OSM HDX stations sampled", "kind": "station"})

    lines = []
    for f in hsr + conv:
        name = f["properties"].get("name")
        if not name:
            continue
        coords = f["geometry"]["coordinates"]
        mid = coords[len(coords)//2]
        lines.append({"name": name, "kind": f["properties"]["kind"], "lon": mid[0], "lat": mid[1]})
    seen, line_idx = set(), []
    for L in sorted(lines, key=lambda x: (0 if x["kind"]=="hsr" else 1, x["name"])):
        if L["name"] in seen:
            continue
        seen.add(L["name"])
        line_idx.append(L)
        if len(line_idx) >= 900:
            break
    st_idx = [{"name": s["properties"]["name"], "kind": "station",
               "lon": s["geometry"]["coordinates"][0],
               "lat": s["geometry"]["coordinates"][1]} for s in st]
    (OUT_DIR / "search-index.json").write_text(
        json.dumps({"lines": line_idx, "stations": st_idx}, ensure_ascii=False, separators=(",", ":"))
    )
    print(f"search index lines={len(line_idx)} stations={len(st_idx)}")
    total = sum(p.stat().st_size for p in OUT_DIR.glob("*.geojson"))
    print(f"total geojson payload {total/1e6:.2f}MB")
    print("DONE")

if __name__ == "__main__":
    main()
