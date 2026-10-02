import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './style.css';
import {
  createCachedTileLayer,
  syncOfflineZoomLimits,
  warmCacheFromBundled,
  isOnline,
} from './tileCache.js';

/** China mainland-ish overview bounds */
const CHINA_BOUNDS = L.latLngBounds([18.0, 73.0], [53.6, 135.0]);

const el = {
  meta: document.getElementById('meta'),
  status: document.getElementById('status'),
  sheet: document.getElementById('sheet'),
  sheetKind: document.getElementById('sheet-kind'),
  sheetTitle: document.getElementById('sheet-title'),
  sheetMeta: document.getElementById('sheet-meta'),
  btnFit: document.getElementById('btn-fit'),
  btnClose: document.getElementById('btn-close'),
  btnSearch: document.getElementById('btn-search'),
  btnSearchClose: document.getElementById('btn-search-close'),
  searchPanel: document.getElementById('search-panel'),
  searchInput: document.getElementById('search-input'),
  searchResults: document.getElementById('search-results'),
  togHsr: document.getElementById('tog-hsr'),
  togConv: document.getElementById('tog-conv'),
  togSta: document.getElementById('tog-sta'),
  offlineBanner: document.getElementById('offline-banner'),
};

/** @type {L.Map} */
let map;
/** @type {L.GeoJSON|null} */
let layerHsr = null;
/** @type {L.GeoJSON|null} */
let layerConv = null;
/** @type {L.LayerGroup|null} */
let layerSta = null;

let counts = { hsr: 0, conventional: 0, stations: 0 };
/** @type {{name:string,kind:string,lon:number,lat:number}[]} */
let searchItems = [];

function showStatus(text) {
  if (!text) {
    el.status.hidden = true;
    el.status.textContent = '';
    return;
  }
  el.status.hidden = false;
  el.status.textContent = text;
}

function updateMeta() {
  const parts = [];
  if (el.togHsr.checked) parts.push(`高铁 ${counts.hsr}`);
  if (el.togConv.checked) parts.push(`普铁 ${counts.conventional}`);
  if (el.togSta.checked) parts.push(`站 ${counts.stations}`);
  el.meta.textContent = parts.join(' · ') || '无图层';
}

function openSheet(kind, title, meta) {
  el.sheetKind.className = `badge ${kind}`;
  el.sheetKind.textContent =
    kind === 'hsr' ? '高铁' : kind === 'station' ? '车站' : '普铁';
  el.sheetTitle.textContent = title || '未命名';
  el.sheetMeta.textContent = meta || '';
  el.sheet.hidden = false;
}

function closeSheet() {
  el.sheet.hidden = true;
}

async function fetchJson(name) {
  const candidates = [
    new URL(`data/${name}`, import.meta.url.replace(/\/src\/.*$/, '/')).href,
    `${import.meta.env.BASE_URL}data/${name}`.replace(/\/{2,}/g, '/').replace(':/', '://'),
    `./data/${name}`,
    `data/${name}`,
  ];
  const tried = new Set();
  let lastErr = null;
  for (const u of candidates) {
    if (!u || tried.has(u)) continue;
    tried.add(u);
    try {
      const res = await fetch(u, { cache: 'no-store' });
      if (!res.ok) throw new Error(`${res.status} ${u}`);
      return await res.json();
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr || new Error(`${name} not found`);
}

function styleHsr(feature) {
  return {
    color: '#60a5fa',
    weight: 2.4,
    opacity: 0.95,
    lineCap: 'round',
    lineJoin: 'round',
  };
}

function styleConv() {
  return {
    color: '#64748b',
    weight: 1.05,
    opacity: 0.7,
    lineCap: 'round',
    lineJoin: 'round',
  };
}

function onEachLine(feature, layer) {
  const name = feature?.properties?.name;
  const kind = feature?.properties?.kind || 'conventional';
  if (name) {
    layer.bindTooltip(name, { sticky: true, opacity: 0.9 });
  }
  layer.on('click', (e) => {
    L.DomEvent.stopPropagation(e);
    openSheet(
      kind,
      name || (kind === 'hsr' ? '高铁线路' : '普速线路'),
      feature?.properties?.id || '',
    );
  });
}

function addStations(fc) {
  layerSta = L.layerGroup();
  const feats = fc.features || [];
  counts.stations = feats.length;
  for (const f of feats) {
    const [lon, lat] = f.geometry.coordinates;
    const name = f.properties?.name || '车站';
    const m = L.marker([lat, lon], {
      icon: L.divIcon({
        className: '',
        html: '<div class="station-marker"></div>',
        iconSize: [8, 8],
        iconAnchor: [4, 4],
      }),
      title: name,
    });
    m.on('click', (e) => {
      L.DomEvent.stopPropagation(e);
      openSheet('station', name, '主要车站（抽样）');
    });
    layerSta.addLayer(m);
  }
}

function syncLayers() {
  if (layerHsr) {
    if (el.togHsr.checked) layerHsr.addTo(map);
    else map.removeLayer(layerHsr);
  }
  if (layerConv) {
    if (el.togConv.checked) layerConv.addTo(map);
    else map.removeLayer(layerConv);
  }
  if (layerSta) {
    if (el.togSta.checked) layerSta.addTo(map);
    else map.removeLayer(layerSta);
  }
  updateMeta();
}

function fitChina() {
  map.fitBounds(CHINA_BOUNDS, { padding: [24, 24], maxZoom: 5 });
}

function openSearch() {
  el.searchPanel.hidden = false;
  el.searchInput.focus();
  renderSearch(el.searchInput.value);
}

function closeSearch() {
  el.searchPanel.hidden = true;
  el.searchInput.value = '';
  el.searchResults.innerHTML = '';
}

function renderSearch(q) {
  const query = (q || '').trim().toLowerCase();
  el.searchResults.innerHTML = '';
  if (!query) {
    const hint = document.createElement('li');
    hint.textContent = '输入线路或车站名称…';
    hint.style.color = 'var(--muted)';
    el.searchResults.appendChild(hint);
    return;
  }
  const hits = searchItems
    .filter((x) => x.name.toLowerCase().includes(query))
    .slice(0, 40);
  if (!hits.length) {
    const empty = document.createElement('li');
    empty.textContent = '无匹配';
    empty.style.color = 'var(--muted)';
    el.searchResults.appendChild(empty);
    return;
  }
  for (const h of hits) {
    const li = document.createElement('li');
    const label =
      h.kind === 'hsr' ? '高铁' : h.kind === 'station' ? '车站' : '普铁';
    li.innerHTML = `<span>${escapeHtml(h.name)}</span><span class="kind ${h.kind}">${label}</span>`;
    li.addEventListener('click', () => {
      closeSearch();
      closeSheet();
      map.setView([h.lat, h.lon], Math.max(map.getZoom(), 7), { animate: true });
      openSheet(h.kind === 'station' ? 'station' : h.kind, h.name, '');
    });
    el.searchResults.appendChild(li);
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}


/** @type {import('leaflet').TileLayer|null} */
let baseTiles = null;
let offlineTileWarned = false;

function setOfflineBanner(show, text) {
  if (!el.offlineBanner) return;
  if (show) {
    el.offlineBanner.hidden = false;
    el.offlineBanner.textContent =
      text ||
      '离线模式：底图仅全国概览缩放（约 z4–z8）；放大需联网或已缓存瓦片';
  } else {
    el.offlineBanner.hidden = true;
  }
}

async function init() {
  map = L.map('map', {
    zoomControl: false,
    attributionControl: true,
    maxZoom: 14,
    minZoom: 3,
  });
  L.control.zoom({ position: 'topright' }).addTo(map);

  baseTiles = createCachedTileLayer(L, { maxZoom: 14 });
  baseTiles.addTo(map);
  syncOfflineZoomLimits(map, baseTiles);

  let tileMissCount = 0;
  baseTiles.on('tileoffline', () => {
    tileMissCount += 1;
    if (offlineTileWarned || tileMissCount < 3) return;
    offlineTileWarned = true;
    setOfflineBanner(true);
  });
  window.addEventListener('online', () => {
    offlineTileWarned = false;
    tileMissCount = 0;
    setOfflineBanner(false);
    syncOfflineZoomLimits(map, baseTiles);
  });
  window.addEventListener('offline', () => {
    syncOfflineZoomLimits(map, baseTiles);
    setOfflineBanner(true);
  });
  if (!isOnline()) setOfflineBanner(true);

  fitChina();
  warmCacheFromBundled().catch(() => {});

  el.btnFit.addEventListener('click', () => {
    closeSheet();
    fitChina();
  });
  el.btnClose.addEventListener('click', closeSheet);
  map.on('click', closeSheet);
  el.togHsr.addEventListener('change', syncLayers);
  el.togConv.addEventListener('change', syncLayers);
  el.togSta.addEventListener('change', syncLayers);
  el.btnSearch.addEventListener('click', openSearch);
  el.btnSearchClose.addEventListener('click', closeSearch);
  el.searchInput.addEventListener('input', () => renderSearch(el.searchInput.value));

  showStatus('加载铁路数据…');
  try {
    const [hsr, conv, sta, idx] = await Promise.all([
      fetchJson('rails-hsr.geojson'),
      fetchJson('rails-conventional.geojson'),
      fetchJson('stations.geojson').catch(() => ({ features: [] })),
      fetchJson('search-index.json').catch(() => ({ lines: [], stations: [] })),
    ]);

    counts.hsr = (hsr.features || []).length;
    counts.conventional = (conv.features || []).length;

    // Conventional under HSR
    layerConv = L.geoJSON(conv, {
      style: styleConv,
      onEachFeature: onEachLine,
      renderer: L.canvas({ padding: 0.5 }),
    });
    layerHsr = L.geoJSON(hsr, {
      style: styleHsr,
      onEachFeature: onEachLine,
      renderer: L.canvas({ padding: 0.5 }),
    });
    addStations(sta);

    syncLayers();

    searchItems = [
      ...(idx.lines || []),
      ...(idx.stations || []),
    ];

    showStatus('');
    updateMeta();
  } catch (e) {
    console.error(e);
    el.meta.textContent = '数据加载失败';
    showStatus('无法读取铁路 GeoJSON，请先运行数据处理脚本');
  }
}

init();
