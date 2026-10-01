#!/usr/bin/env python3
"""Fetch China HSR (highspeed=yes) via Overpass in lat/lon grid chunks."""
from __future__ import annotations
import json, time, urllib.request, urllib.error, urllib.parse, sys
from pathlib import Path

OUT = Path("/tmp/rail-data/hsr_raw")
OUT.mkdir(parents=True, exist_ok=True)
# Prefer working mirror first
ENDPOINTS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# ~4x6 deg tiles over China
LATS = list(range(18, 55, 4))  # 18..54
LONS = list(range(73, 136, 6))

def tiles():
    pairs = []
    for i, south in enumerate(LATS[:-1]):
        north = LATS[i + 1]
        for j, west in enumerate(LONS[:-1]):
            east = min(LONS[j + 1], 135)
            pairs.append((south, west, north, east))
        if LONS[-1] < 135:
            pairs.append((south, LONS[-1], north, 135))
    return pairs

QUERY = """[out:json][timeout:60];
way["railway"="rail"]["highspeed"="yes"]({s},{w},{n},{e});
out geom;"""

def post(url: str, data: str, timeout: int = 100) -> bytes:
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode({"data": data}).encode(),
        method="POST",
        headers={"User-Agent": "railview-build/1.0 (huming0618)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()

def fetch_tile(s, w, n, e):
    q = QUERY.format(s=s, w=w, n=n, e=e)
    last = None
    for ep in ENDPOINTS:
        try:
            raw = post(ep, q)
            if raw.lstrip().startswith(b"<"):
                raise RuntimeError(f"HTML error: {raw[:200]!r}")
            data = json.loads(raw)
            if "elements" not in data:
                raise RuntimeError(f"no elements: {str(data)[:200]}")
            return data
        except Exception as ex:
            last = ex
            print(f"  fail {ep}: {ex}", flush=True)
            time.sleep(3)
    raise RuntimeError(f"all endpoints failed for {s},{w},{n},{e}: {last}")

def way_to_feature(el):
    geom = el.get("geometry") or []
    if len(geom) < 2:
        return None
    coords = [[p["lon"], p["lat"]] for p in geom]
    tags = el.get("tags") or {}
    return {
        "type": "Feature",
        "properties": {
            "id": f"way/{el['id']}",
            "name": tags.get("name") or tags.get("name:zh") or tags.get("name:en"),
            "highspeed": tags.get("highspeed"),
            "railway": tags.get("railway"),
            "usage": tags.get("usage"),
            "service": tags.get("service"),
            "maxspeed": tags.get("maxspeed"),
            "kind": "hsr",
        },
        "geometry": {"type": "LineString", "coordinates": coords},
    }

def main():
    # Clear bad caches
    for p in OUT.glob("*.json"):
        try:
            d = json.loads(p.read_text())
            if "elements" not in d:
                p.unlink()
        except Exception:
            p.unlink()
    all_feats = {}
    tlist = tiles()
    print(f"tiles: {len(tlist)}", flush=True)
    for i, (s, w, n, e) in enumerate(tlist):
        key = f"{s}_{w}_{n}_{e}"
        cache = OUT / f"{key}.json"
        print(f"[{i+1}/{len(tlist)}] {key}", flush=True)
        if cache.exists() and cache.stat().st_size > 50:
            try:
                data = json.loads(cache.read_text())
                if "elements" not in data:
                    raise ValueError("bad cache")
            except Exception:
                cache.unlink(missing_ok=True)
                data = None
        else:
            data = None
        if data is None:
            for attempt in range(4):
                try:
                    data = fetch_tile(s, w, n, e)
                    cache.write_text(json.dumps(data))
                    break
                except Exception as ex:
                    print(f"  retry {attempt+1}: {ex}", flush=True)
                    time.sleep(4 * (attempt + 1))
            else:
                print(f"  SKIP {key}", flush=True)
                continue
            time.sleep(0.8)
        els = data.get("elements") or []
        n_new = 0
        for el in els:
            if el.get("type") != "way":
                continue
            wid = el["id"]
            if wid in all_feats:
                continue
            feat = way_to_feature(el)
            if feat:
                all_feats[wid] = feat
                n_new += 1
        print(f"  elements={len(els)} new={n_new} total={len(all_feats)}", flush=True)
    fc = {"type": "FeatureCollection", "features": list(all_feats.values())}
    out = Path("/tmp/rail-data/hsr_merged.geojson")
    out.write_text(json.dumps(fc, ensure_ascii=False))
    print(f"wrote {out} features={len(fc['features'])}", flush=True)

if __name__ == "__main__":
    main()
