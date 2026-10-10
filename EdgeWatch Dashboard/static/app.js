const POLL_INTERVAL_MS = 5000;

// Decorative only -- our real nodes don't have geographic data.
const NODE_FLAVOR = {
  'node-01': { city: 'Server Rack 1', dc: 'DC-04' },
  'node-02': { city: 'Server Rack 2', dc: 'DC-02' },
  'node-03': { city: 'Server Rack 3', dc: 'DC-01' },
  'node-04': { city: 'Toronto', dc: 'DC-03' },
  'node-05': { city: 'Seoul', dc: 'DC-07' },
  'node-06': { city: 'Helsinki', dc: 'DC-06' },
};

const el = {
  viewFleet: document.getElementById('view-fleet'),
  viewDetail: document.getElementById('view-detail'),
  clock: document.getElementById('clock'),
  crumbCurrent: document.getElementById('crumb-current'),

  btnRefresh: document.getElementById('btn-refresh'),
  fleetSummaryText: document.getElementById('fleet-summary-text'),
  confidenceValue: document.getElementById('confidence-value'),
  syncedValue: document.getElementById('synced-value'),
  statOnline: document.getElementById('stat-online'),
  barOnline: document.getElementById('bar-online'),
  statAttention: document.getElementById('stat-attention'),
  barAttention: document.getElementById('bar-attention'),
  statRisk: document.getElementById('stat-risk'),
  barRisk: document.getElementById('bar-risk'),
  nodeCountLabel: document.getElementById('node-count-label'),
  grid: document.getElementById('node-grid'),
  emptyState: document.getElementById('empty-state'),
  footerSync: document.getElementById('footer-sync'),

  backBtn: document.getElementById('btn-back'),
  detailHeaderPanel: document.getElementById('detail-header-panel'),
  detailEyebrow: document.getElementById('detail-eyebrow'),
  detailDot: document.getElementById('detail-dot'),
  detailTitle: document.getElementById('detail-title'),
  detailBadgeInline: document.getElementById('detail-badge-inline'),
  detailSubtitle: document.getElementById('detail-subtitle'),
  readoutLiveTag: document.getElementById('readout-live-tag'),
  detailMetrics: document.getElementById('detail-metrics'),
  riskScoreValue: document.getElementById('risk-score-value'),
  riskScoreTag: document.getElementById('risk-score-tag'),
  riskGradientFill: document.getElementById('risk-gradient-fill'),
  detailReasoning: document.getElementById('detail-reasoning'),
  perfMetricName: document.getElementById('perf-metric-name'),
  perfRangeLabel: document.getElementById('perf-range-label'),
  rangeToggle: document.getElementById('range-toggle'),
  detailChart: document.getElementById('detail-chart'),
  actionPanel: document.getElementById('action-panel'),
  actionBadgeText: document.getElementById('action-badge-text'),
  actionDesc: document.getElementById('action-desc'),
};

let currentNodeId = null;
let currentRange = '60s';

const historyCache = new Map();
const historyRequests = new Map();

// ============================================================
// HELPERS
// ============================================================

function fmt(value, digits = 2, unit = '') {
  if (value === null || value === undefined) return '—';
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return number.toFixed(digits) + (unit ? '<span class="unit">' + unit + '</span>' : '');
}

function severityClass(sev) {
  return 'severity-' + sev;
}

function badgeClass(sev) {
  if (sev === 'critical') return 'badge-critical';
  if (sev === 'warn') return 'badge-warn';
  if (sev === 'offline') return 'badge-offline';
  return 'badge-ok';
}

function labelize(nodeId) {
  const num = parseInt(nodeId.split('-')[1], 10);
  return 'Node ' + String(num).padStart(2, '0');
}

function connTag(connectivity) {
  if (connectivity === 'live') return { text: '📶 LIVE', cls: 'conn-live' };
  if (connectivity === 'last_seen') return { text: '📵 LAST SEEN', cls: '' };
  return { text: '⊘ OFFLINE', cls: '' };
}

// ============================================================
// CLOCK
// ============================================================

function tickClock() {
  const now = new Date();
  el.clock.textContent = now.toISOString().substr(11, 8);
}

setInterval(tickClock, 1000);
tickClock();

// ============================================================
// NODE CARD HTML
// ============================================================

function createNodeCard(node) {
  const flavor = NODE_FLAVOR[node.node_id] || { city: '—', dc: '—' };
  const tag = connTag(node.connectivity);

  return '<button class="node-card ' + severityClass(node.severity) + '" data-node="' + node.node_id + '">'
    + '<div class="card-top-row">'
    +   '<span class="card-eyebrow">COMPUTE NODE /' + node.node_id.split('-')[1] + '</span>'
    +   '<span class="status-dot"></span>'
    + '</div>'
    + '<p class="node-name">' + labelize(node.node_id) + '</p>'
    + '<div class="node-loc-row">'
    +   '<span class="node-loc">' + flavor.city + ' / ' + flavor.dc + '</span>'
    +   '<span class="conn-tag ' + tag.cls + '">' + tag.text + '</span>'
    + '</div>'
    + '<div class="node-metrics-grid">'
    +   '<span>Voltage <span class="m-value" data-field="voltage">' + fmt(node.voltage_v, 2, 'V') + '</span></span>'
    +   '<span>Temp <span class="m-value" data-field="temperature">' + fmt(node.temperature_c, 1, '°C') + '</span></span>'
    +   '<span>Vibration <span class="m-value" data-field="vibration">' + fmt(node.vibration_g, 2, 'g') + '</span></span>'
    +   '<span>RSSI <span class="m-value" data-field="rssi">' + (node.rssi_dbm !== null && node.rssi_dbm !== undefined ? node.rssi_dbm : '—') + '<span class="unit">dBm</span></span></span>'
    +   '<span class="full-row">CPU load <span class="m-value" data-field="cpu">' + fmt(node.cpu_load_pct, 0, '%') + '</span></span>'
    + '</div>'
    + '<p class="sparkline-label">60 SEC TREND</p>'
    + '<div class="sparkline-svg" data-sparkline="' + node.node_id + '" data-severity="' + node.severity + '"></div>'
    + '<div class="card-bottom-row">'
    +   '<span class="badge ' + badgeClass(node.severity) + '" data-field="badge">' + node.status_label + '</span>'
    +   '<span class="inspect-link">Inspect ↗</span>'
    + '</div>'
    + '</button>';
}

// ============================================================
// UPDATE EXISTING NODE CARD
// ============================================================

function updateNodeCard(card, node) {
  const flavor = NODE_FLAVOR[node.node_id] || { city: '—', dc: '—' };
  const tag = connTag(node.connectivity);

  card.className = 'node-card ' + severityClass(node.severity);

  const voltage = card.querySelector('[data-field="voltage"]');
  const temperature = card.querySelector('[data-field="temperature"]');
  const vibration = card.querySelector('[data-field="vibration"]');
  const rssi = card.querySelector('[data-field="rssi"]');
  const cpu = card.querySelector('[data-field="cpu"]');
  const badge = card.querySelector('[data-field="badge"]');

  if (voltage) voltage.innerHTML = fmt(node.voltage_v, 2, 'V');
  if (temperature) temperature.innerHTML = fmt(node.temperature_c, 1, '°C');
  if (vibration) vibration.innerHTML = fmt(node.vibration_g, 2, 'g');
  if (rssi) rssi.innerHTML = (node.rssi_dbm !== null && node.rssi_dbm !== undefined ? node.rssi_dbm : '—') + '<span class="unit">dBm</span>';
  if (cpu) cpu.innerHTML = fmt(node.cpu_load_pct, 0, '%');

  const location = card.querySelector('.node-loc');
  if (location) location.textContent = flavor.city + ' / ' + flavor.dc;

  const connection = card.querySelector('.conn-tag');
  if (connection) {
    connection.textContent = tag.text;
    connection.className = 'conn-tag ' + tag.cls;
  }

  if (badge) {
    badge.textContent = node.status_label;
    badge.className = 'badge ' + badgeClass(node.severity);
  }

  const sparkline = card.querySelector('[data-sparkline]');
  if (sparkline) sparkline.dataset.severity = node.severity;
}

// ============================================================
// CREATE / UPDATE FLEET
// ============================================================

function renderFleet(data) {
  const total = Number(data.nodes_total) || 0;
  const online = Number(data.nodes_online) || 0;

  el.nodeCountLabel.textContent = total + ' TOTAL / ' + online + ' ONLINE';

  el.fleetSummaryText.textContent = data.fleet_summary || 'Waiting for the first analysis cycle…';

  el.confidenceValue.textContent =
    (data.confidence !== null && data.confidence !== undefined)
      ? data.confidence + '%'
      : '—';

  const updated = new Date(data.updated_at);
  if (!Number.isNaN(updated.getTime())) {
    const syncedTime = updated.toISOString().substr(11, 8);
    el.syncedValue.textContent = syncedTime + ' UTC';
    el.footerSync.textContent = syncedTime + ' UTC';
  }

  el.statOnline.innerHTML = online + '<span class="stat-total">/' + total + '</span>';
  el.barOnline.style.width = total > 0 ? ((online / total) * 100) + '%' : '0%';

  const attention = Number(data.nodes_attention) || 0;
  el.statAttention.textContent = String(attention).padStart(2, '0');
  el.barAttention.style.width = total > 0 ? ((attention / total) * 100) + '%' : '0%';

  const avgRisk = Number(data.avg_risk) || 0;
  el.statRisk.innerHTML = avgRisk + '<span class="stat-total">/100</span>';
  el.barRisk.style.width = Math.max(0, Math.min(100, avgRisk)) + '%';
  el.barRisk.className = 'stat-bar-fill ' + (avgRisk >= 60 ? 'stat-bar-warn' : 'stat-bar-ok');

  if (!Array.isArray(data.nodes) || data.nodes.length === 0) {
    el.emptyState.hidden = false;
    if (el.grid.children.length > 0) el.grid.innerHTML = '';
    return;
  }

  el.emptyState.hidden = true;

  const existingCards = new Map();
  el.grid.querySelectorAll('.node-card').forEach(function(card) {
    if (card.dataset.node) existingCards.set(card.dataset.node, card);
  });

  const incomingIds = new Set(data.nodes.map(function(node) { return node.node_id; }));

  data.nodes.forEach(function(node) {
    let card = existingCards.get(node.node_id);

    if (!card) {
      const wrapper = document.createElement('div');
      wrapper.innerHTML = createNodeCard(node).trim();
      card = wrapper.firstElementChild;
      if (!card) return;

      card.addEventListener('click', function() { openDetail(node.node_id); });
      el.grid.appendChild(card);

      const sparkline = card.querySelector('[data-sparkline]');
      if (sparkline) renderSparkline(sparkline, node.node_id, node.severity);
    } else {
      updateNodeCard(card, node);
    }
  });

  existingCards.forEach(function(card, nodeId) {
    if (!incomingIds.has(nodeId)) card.remove();
  });

  data.nodes.forEach(function(node) {
    const card = el.grid.querySelector('.node-card[data-node="' + CSS.escape(node.node_id) + '"]');
    if (!card) return;
    const sparkline = card.querySelector('[data-sparkline]');
    if (!sparkline) return;
    if (!sparkline.querySelector('svg')) {
      renderSparkline(sparkline, node.node_id, node.severity);
    }
  });
}

// ============================================================
// HISTORY / SPARKLINE
// ============================================================

async function renderSparkline(container, nodeId, severity) {
  if (!container) return;

  const cacheKey = nodeId + ':60s';
  const cached = historyCache.get(cacheKey);

  if (cached && Array.isArray(cached.readings) && cached.readings.length >= 2) {
    drawSparkline(container, cached.readings, cached.metric_key, severity);
  }

  if (historyRequests.has(cacheKey)) return;

  const request = fetch('/api/node/' + encodeURIComponent(nodeId) + '/history?range=60s', { cache: 'no-store' })
    .then(function(response) {
      if (!response.ok) throw new Error('History request failed: HTTP ' + response.status);
      return response.json();
    })
    .then(function(result) {
      if (!result || !Array.isArray(result.readings)) throw new Error('Invalid history response');

      historyCache.set(cacheKey, result);

      const currentCard = el.grid.querySelector('.node-card[data-node="' + CSS.escape(nodeId) + '"]');
      if (!currentCard) return;

      const currentContainer = currentCard.querySelector('[data-sparkline]');
      if (!currentContainer) return;

      const currentSeverity = currentContainer.dataset.severity || severity;
      drawSparkline(currentContainer, result.readings, result.metric_key, currentSeverity);
    })
    .catch(function(error) {
      console.warn('History unavailable for ' + nodeId + ':', error);
    })
    .finally(function() {
      historyRequests.delete(cacheKey);
    });

  historyRequests.set(cacheKey, request);
  await request;
}

// ============================================================
// DRAW SPARKLINE
// ============================================================

function drawSparkline(container, readings, metricKey, severity) {
  if (!container || !Array.isArray(readings)) return;

  const values = readings
    .map(function(r) { return r[metricKey]; })
    .filter(function(v) { return v !== null && v !== undefined && Number.isFinite(Number(v)); })
    .map(Number);

  if (values.length < 2) return;

  const w = 300;
  const h = 44;
  const min = Math.min.apply(null, values);
  const max = Math.max.apply(null, values);
  const range = (max - min) || 1;

  const points = values.map(function(value, index) {
    const x = (index / (values.length - 1)) * w;
    const y = h - ((value - min) / range) * (h - 6) - 3;
    return [x, y];
  });

  const path = points.map(function(point, index) {
    return (index === 0 ? 'M' : 'L') + point[0].toFixed(1) + ',' + point[1].toFixed(1);
  }).join(' ');

  let color;
  if (severity === 'critical') color = '#E8604A';
  else if (severity === 'warn') color = '#E8A33D';
  else if (severity === 'offline') color = '#6B7A82';
  else color = '#4FD1C5';

  const last = points[points.length - 1];

  container.innerHTML = '<svg viewBox="0 0 ' + w + ' ' + h + '" width="100%" height="' + h + '" preserveAspectRatio="none" aria-hidden="true">'
    + '<path d="' + path + '" fill="none" stroke="' + color + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
    + '<circle cx="' + last[0] + '" cy="' + last[1] + '" r="3" fill="' + color + '"/>'
    + '</svg>';
}

// ============================================================
// NODE DETAIL
// ============================================================

async function openDetail(nodeId) {
  currentNodeId = nodeId;
  currentRange = '60s';

  el.crumbCurrent.textContent = labelize(nodeId);
  el.viewFleet.hidden = true;
  el.viewDetail.hidden = false;

  document.querySelectorAll('.range-btn').forEach(function(button) {
    button.classList.toggle('active', button.dataset.range === '60s');
  });

  await refreshDetail();
}

function closeDetail() {
  currentNodeId = null;
  el.crumbCurrent.textContent = 'Fleet overview';
  el.viewDetail.hidden = true;
  el.viewFleet.hidden = false;
}

function riskTag(score) {
  if (score === null || score === undefined) return { text: 'Nominal', cls: 'tag-nominal' };
  if (score >= 70) return { text: 'Immediate attention', cls: 'tag-critical' };
  if (score >= 40) return { text: 'Monitor', cls: 'tag-monitor' };
  return { text: 'Nominal', cls: 'tag-nominal' };
}

// ============================================================
// DETAIL PAGE
// ============================================================

async function refreshDetail() {
  if (!currentNodeId) return;

  const nodeIdAtRequest = currentNodeId;
  const rangeAtRequest = currentRange;

  try {
    const fleetPromise = fetch('/api/fleet', { cache: 'no-store' }).then(function(response) {
      if (!response.ok) throw new Error('Fleet request failed: HTTP ' + response.status);
      return response.json();
    });

    const historyPromise = fetch(
      '/api/node/' + encodeURIComponent(nodeIdAtRequest) + '/history?range=' + encodeURIComponent(rangeAtRequest),
      { cache: 'no-store' }
    ).then(function(response) {
      if (!response.ok) throw new Error('History request failed: HTTP ' + response.status);
      return response.json();
    });

    const results = await Promise.all([fleetPromise, historyPromise]);
    const fleetRes = results[0];
    const historyRes = results[1];

    if (currentNodeId !== nodeIdAtRequest || currentRange !== rangeAtRequest) return;

    const node = fleetRes.nodes.find(function(n) { return n.node_id === nodeIdAtRequest; });
    if (!node) return;

    const flavor = NODE_FLAVOR[node.node_id] || { city: '—', dc: '—' };
    const tag = connTag(node.connectivity);
    const sevClass = severityClass(node.severity);

    el.detailHeaderPanel.className = 'detail-header-panel ' + sevClass;
    el.detailEyebrow.innerHTML = '02 <span class="eyebrow-dim">NODE DIAGNOSTICS</span> / ' + node.node_id.toUpperCase();
    el.detailTitle.textContent = labelize(node.node_id);
    el.detailBadgeInline.className = 'badge ' + badgeClass(node.severity);
    el.detailBadgeInline.textContent = node.status_label;

    const rootStyle = getComputedStyle(document.documentElement);
    const severityVariable =
      node.severity === 'critical' ? '--critical'
      : node.severity === 'warn' ? '--warn'
      : node.severity === 'offline' ? '--offline'
      : '--ok';

    el.detailDot.style.background = rootStyle.getPropertyValue(severityVariable);

    el.detailSubtitle.textContent = flavor.city + ' / ' + flavor.dc + ' · '
      + (node.connectivity === 'live' ? 'Streaming telemetry'
         : node.connectivity === 'last_seen' ? 'Signal delayed'
         : 'No current telemetry');

    el.readoutLiveTag.textContent = tag.text
      .replace('📶 ', '• ')
      .replace('📵 ', '• ')
      .replace('⊘ ', '• ');

    el.readoutLiveTag.className = 'live-tag' + (node.connectivity !== 'live' ? ' stale' : '');

    el.detailMetrics.innerHTML =
      '<div><dt>Voltage</dt><dd>' + fmt(node.voltage_v, 2, 'V') + '</dd></div>'
      + '<div><dt>Temperature</dt><dd>' + fmt(node.temperature_c, 1, '°C') + '</dd></div>'
      + '<div><dt>Vibration</dt><dd>' + fmt(node.vibration_g, 3, 'g') + '</dd></div>'
      + '<div><dt>RSSI signal</dt><dd>' + (node.rssi_dbm !== null && node.rssi_dbm !== undefined ? node.rssi_dbm : '—') + '<span class="unit">dBm</span></dd></div>'
      + '<div><dt>CPU load</dt><dd>' + fmt(node.cpu_load_pct, 0, '%') + '</dd></div>'
      + '<div><dt>Uptime</dt><dd>' + node.uptime_display + '</dd></div>';

    const rt = riskTag(node.risk_score);
    el.riskScoreValue.textContent = node.risk_score !== null && node.risk_score !== undefined ? node.risk_score : '—';
    el.riskScoreTag.textContent = rt.text;
    el.riskScoreTag.className = 'risk-score-tag ' + rt.cls;
    el.riskGradientFill.style.width = (node.risk_score !== null && node.risk_score !== undefined ? node.risk_score : 0) + '%';

    el.detailReasoning.textContent = node.reasoning
      || 'No analysis yet for this node — waiting on the next LLM analysis cycle.';

    if (historyRes && Array.isArray(historyRes.readings)) {
      el.perfMetricName.textContent = historyRes.metric_label || 'Metric';

      const rangeLabelText = { '60s': 'last 60 sec', '5m': 'last 5 min', '1h': 'last 1 hr' }[currentRange] || currentRange;
      el.perfRangeLabel.textContent = '/ ' + rangeLabelText;

      renderChart(historyRes.readings, historyRes.metric_key, node.severity);
    }

    if (node.severity === 'warn' || node.severity === 'critical') {
      el.actionPanel.hidden = false;
      el.actionBadgeText.textContent = node.status_label;

      const failureWindow = node.predicted_failure_window;
      el.actionDesc.innerHTML = failureWindow
        ? 'At the current rate, the model estimates the node may reach its protection threshold in <span class="highlight">' + failureWindow + '</span>.'
        : (node.reasoning || 'The model has flagged this node for review.');
    } else {
      el.actionPanel.hidden = true;
    }

  } catch (error) {
    console.error('Detail refresh failed:', error);
  }
}

// ============================================================
// DETAIL CHART
// ============================================================

function renderChart(readings, metricKey, severity) {
  const svg = el.detailChart;
  svg.innerHTML = '';

  const ns = 'http://www.w3.org/2000/svg';

  const values = readings
    .map(function(r) { return r[metricKey]; })
    .filter(function(v) { return v !== null && v !== undefined && Number.isFinite(Number(v)); })
    .map(Number);

  if (values.length < 2) {
    const text = document.createElementNS(ns, 'text');
    text.setAttribute('x', '280');
    text.setAttribute('y', '100');
    text.setAttribute('text-anchor', 'middle');
    text.setAttribute('fill', '#576870');
    text.setAttribute('font-size', '12');
    text.setAttribute('font-family', 'IBM Plex Mono');
    text.textContent = 'not enough data yet for this range';
    svg.appendChild(text);
    return;
  }

  const w = 560;
  const h = 200;
  const padX = 16;
  const padTop = 16;
  const padBottom = 30;
  const min = Math.min.apply(null, values);
  const max = Math.max.apply(null, values);
  const range = (max - min) || 1;
  const plotH = h - padTop - padBottom;

  const points = values.map(function(value, index) {
    const x = padX + (index / (values.length - 1)) * (w - padX * 2);
    const y = padTop + plotH - ((value - min) / range) * plotH;
    return [x, y];
  });

  let color;
  if (severity === 'critical') color = '#E8604A';
  else if (severity === 'warn') color = '#E8A33D';
  else if (severity === 'offline') color = '#6B7A82';
  else color = '#4FD1C5';

  const linePath = points.map(function(point, index) {
    return (index === 0 ? 'M' : 'L') + point[0].toFixed(1) + ',' + point[1].toFixed(1);
  }).join(' ');

  const areaPath = linePath
    + ' L' + points[points.length - 1][0].toFixed(1) + ',' + (padTop + plotH)
    + ' L' + points[0][0].toFixed(1) + ',' + (padTop + plotH) + ' Z';

  const gradId = 'chartGrad-' + Date.now() + '-' + Math.random().toString(36).slice(2);

  const defs = document.createElementNS(ns, 'defs');
  defs.innerHTML = '<linearGradient id="' + gradId + '" x1="0" y1="0" x2="0" y2="1">'
    + '<stop offset="0%" stop-color="' + color + '" stop-opacity="0.35"/>'
    + '<stop offset="100%" stop-color="' + color + '" stop-opacity="0"/>'
    + '</linearGradient>';
  svg.appendChild(defs);

  const midY = padTop + plotH / 2;
  const thresholdLine = document.createElementNS(ns, 'line');
  thresholdLine.setAttribute('x1', padX);
  thresholdLine.setAttribute('x2', w - padX);
  thresholdLine.setAttribute('y1', midY);
  thresholdLine.setAttribute('y2', midY);
  thresholdLine.setAttribute('stroke', '#2C3940');
  thresholdLine.setAttribute('stroke-width', '1');
  thresholdLine.setAttribute('stroke-dasharray', '3,4');
  svg.appendChild(thresholdLine);

  const area = document.createElementNS(ns, 'path');
  area.setAttribute('d', areaPath);
  area.setAttribute('fill', 'url(#' + gradId + ')');
  area.setAttribute('stroke', 'none');
  svg.appendChild(area);

  const line = document.createElementNS(ns, 'path');
  line.setAttribute('d', linePath);
  line.setAttribute('fill', 'none');
  line.setAttribute('stroke', color);
  line.setAttribute('stroke-width', '2.5');
  line.setAttribute('stroke-linecap', 'round');
  line.setAttribute('stroke-linejoin', 'round');
  svg.appendChild(line);

  const last = points[points.length - 1];
  const dot = document.createElementNS(ns, 'circle');
  dot.setAttribute('cx', last[0]);
  dot.setAttribute('cy', last[1]);
  dot.setAttribute('r', '4');
  dot.setAttribute('fill', color);
  svg.appendChild(dot);

  const rangeLabels = {
    '60s': ['-60s', '-45s', '-30s', '-15s', 'NOW'],
    '5m':  ['-5m', '-3.75m', '-2.5m', '-1.25m', 'NOW'],
    '1h':  ['-1h', '-45m', '-30m', '-15m', 'NOW'],
  }[currentRange];

  if (rangeLabels) {
    rangeLabels.forEach(function(label, index) {
      const x = padX + (index / (rangeLabels.length - 1)) * (w - padX * 2);
      const text = document.createElementNS(ns, 'text');
      text.setAttribute('x', x);
      text.setAttribute('y', h - 10);
      text.setAttribute('text-anchor',
        index === 0 ? 'start'
        : index === rangeLabels.length - 1 ? 'end'
        : 'middle');
      text.setAttribute('fill', '#576870');
      text.setAttribute('font-size', '10');
      text.setAttribute('font-family', 'IBM Plex Mono');
      text.textContent = label;
      svg.appendChild(text);
    });
  }
}

// ============================================================
// RANGE BUTTONS
// ============================================================

el.rangeToggle.addEventListener('click', function(event) {
  const button = event.target.closest('.range-btn');
  if (!button) return;

  currentRange = button.dataset.range;

  document.querySelectorAll('.range-btn').forEach(function(btn) {
    btn.classList.toggle('active', btn === button);
  });

  refreshDetail();
});

// ============================================================
// POLLING
// ============================================================

let pollInProgress = false;

async function poll() {
  if (pollInProgress) return;
  pollInProgress = true;

  try {
    if (currentNodeId) {
      await refreshDetail();
    } else {
      const response = await fetch('/api/fleet', { cache: 'no-store' });
      if (!response.ok) throw new Error('Fleet request failed: HTTP ' + response.status);
      const data = await response.json();
      renderFleet(data);
    }
  } catch (error) {
    console.error('EdgeWatch dashboard poll failed:', error);
  } finally {
    pollInProgress = false;
  }
}

// ============================================================
// BUTTONS
// ============================================================

el.backBtn.addEventListener('click', closeDetail);

el.btnRefresh.addEventListener('click', function() {
  el.btnRefresh.textContent = '↻ Refreshing…';
  poll().finally(function() {
    el.btnRefresh.textContent = '↻ Refresh stream';
  });
});

// ============================================================
// START
// ============================================================

poll();
setInterval(poll, POLL_INTERVAL_MS);
