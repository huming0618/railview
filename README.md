# 中国铁路 · railview

Nationwide China railway overview map (高铁 + 普速), mobile-friendly, Vite + Leaflet.

**Live:** https://huming0618.github.io/railview/

## Features

- Dark UI, fits China on one phone screen
- Toggle 高铁 / 普铁 / 主要站
- Search major named lines and stations
- Precomputed GeoJSON (no live Overpass)

## Data

| Layer | Source | Approx. features |
|-------|--------|------------------|
| 高铁 HSR | Geofabrik China OSM PBF → `highspeed=yes` + `railway=rail` (osmium), service tracks removed, simplified | ~58k line segments |
| 普铁 Conventional | Same PBF `railway=rail` excluding HSR/service, simplified & thinned for overview | ~32k line segments |
| Stations | HOT OSM HDX China railways export (sampled hubs) | ~320 |

Payload target ≈ under 15 MB GeoJSON total.

Regenerate locally (needs `osmium`, `shapely`, `ijson`, Geofabrik PBF under `/tmp/rail-data/`):

```bash
python3 scripts/process_rails.py
```

## Dev

```bash
npm install
npm run dev
```

GitHub Pages uses Vite `base: '/railview/'`.

## License

Map data © OpenStreetMap contributors (ODbL). Code MIT.

## Android (Capacitor offline)

```bash
npm install
npm run seed-offline-tiles   # China overview z4–z8 into public/offline-tiles
npm run build:android
cd android && ./gradlew assembleDebug
```

App id: `com.huming.railview`. Offline basemap covers national overview zooms only; higher zooms need network / Cache API.
