/**
 * forecast.js — Review Forecast D3 v7 bar chart
 *
 * Fetches /api/forecast?range=<range_type> and renders a bar chart.
 * Overdue bucket is always displayed first (leftmost) in red.
 * Bar colour by avg_mastery: <40 red, <70 amber, >=70 green.
 * Clicking a bar fetches /api/forecast/concepts?... → populates detail table.
 */

/* ── Constants ─────────────────────────────────────────────────────────── */
const RED    = '#ef4444';
const AMBER  = '#f59e0b';
const GREEN  = '#22c55e';
const GREY   = '#6b7280';

function masteryColor(avgMastery) {
  if (avgMastery < 40) return RED;
  if (avgMastery < 70) return AMBER;
  return GREEN;
}

/* ── State ──────────────────────────────────────────────────────────────── */
let currentRange = 'weeks';
let currentBucket = null;  // selected bucket_key or 'overdue'

/* ── Bootstrap ─────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  // Wire toggle buttons
  document.querySelectorAll('#forecast-range-toggle .filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#forecast-range-toggle .filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentRange = btn.dataset.range;
      currentBucket = null;
      hideConcepts();
      loadForecast(currentRange);
    });
  });

  loadForecast(currentRange);
});

/* ── Data loading ──────────────────────────────────────────────────────── */
async function loadForecast(range) {
  const chartEl = document.getElementById('forecast-chart');
  chartEl.textContent = 'Loading…';

  try {
    const res = await fetch(`/api/forecast?range=${encodeURIComponent(range)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderChart(data);
  } catch (err) {
    chartEl.textContent = `Error loading forecast: ${err.message}`;
  }
}

/* ── Chart rendering ───────────────────────────────────────────────────── */
function renderChart(data) {
  const chartEl = document.getElementById('forecast-chart');
  chartEl.textContent = '';  // clear

  // Build unified bar list: Overdue leading bar + rolling buckets
  const bars = [];
  if (data.overdue_count > 0 || true) {  // always show overdue slot
    bars.push({
      label: 'Overdue',
      bucket_key: 'overdue',
      count: data.overdue_count,
      avg_mastery: 0,
      is_overdue: true,
    });
  }
  for (const b of data.buckets) {
    bars.push({ ...b, is_overdue: false });
  }

  // Chart dimensions
  const margin = { top: 16, right: 16, bottom: 64, left: 44 };
  const totalWidth = Math.max(chartEl.clientWidth || 600, 400);
  const width  = totalWidth - margin.left - margin.right;
  const height = 220;

  const svg = d3.select(chartEl)
    .append('svg')
      .attr('width', totalWidth)
      .attr('height', height + margin.top + margin.bottom)
    .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

  // Scales
  const x = d3.scaleBand()
    .domain(bars.map(b => b.bucket_key))
    .range([0, width])
    .padding(0.2);

  const maxCount = d3.max(bars, b => b.count) || 1;
  const y = d3.scaleLinear()
    .domain([0, maxCount * 1.15])
    .range([height, 0])
    .nice();

  // Gridlines
  svg.append('g')
    .attr('class', 'grid')
    .call(
      d3.axisLeft(y)
        .tickSize(-width)
        .tickFormat('')
        .ticks(5)
    )
    .selectAll('line')
      .style('stroke', 'var(--border, #e5e7eb)')
      .style('stroke-dasharray', '3,3');
  svg.select('.grid .domain').remove();

  // Y axis
  svg.append('g')
    .call(d3.axisLeft(y).ticks(5).tickFormat(d3.format('d')))
    .selectAll('text')
      .style('font-size', '11px')
      .style('fill', 'var(--text2, #6b7280)');

  // Bars
  svg.selectAll('.bar')
    .data(bars)
    .join('rect')
      .attr('class', 'bar')
      .attr('x', b => x(b.bucket_key))
      .attr('y', b => y(b.count))
      .attr('width', x.bandwidth())
      .attr('height', b => height - y(b.count))
      .attr('fill', b => {
        if (b.is_overdue) return b.count > 0 ? RED : GREY;
        return b.count === 0 ? GREY : masteryColor(b.avg_mastery);
      })
      .attr('rx', 3)
      .style('cursor', 'pointer')
      .style('opacity', b => b.bucket_key === currentBucket ? 1.0 : 0.85)
      .on('mouseover', function(event, b) {
        d3.select(this).style('opacity', 1);
        showTooltip(event, b);
      })
      .on('mouseout', function(event, b) {
        d3.select(this).style('opacity', b.bucket_key === currentBucket ? 1.0 : 0.85);
        hideTooltip();
      })
      .on('click', (event, b) => {
        currentBucket = b.bucket_key;
        // Re-render to update selection appearance
        renderChart(data);
        loadBucketConcepts(currentRange, b.bucket_key, b.label);
      });

  // Count labels above bars
  svg.selectAll('.bar-label')
    .data(bars)
    .join('text')
      .attr('class', 'bar-label')
      .attr('x', b => x(b.bucket_key) + x.bandwidth() / 2)
      .attr('y', b => y(b.count) - 4)
      .attr('text-anchor', 'middle')
      .style('font-size', '11px')
      .style('fill', 'var(--text2, #6b7280)')
      .text(b => b.count > 0 ? b.count : '');

  // X axis labels
  svg.append('g')
    .attr('transform', `translate(0,${height})`)
    .call(d3.axisBottom(x).tickFormat(k => {
      const bar = bars.find(b => b.bucket_key === k);
      return bar ? bar.label : k;
    }))
    .selectAll('text')
      .style('font-size', '11px')
      .style('fill', 'var(--text2, #6b7280)')
      .attr('transform', 'rotate(-30)')
      .style('text-anchor', 'end');
}

/* ── Tooltip ────────────────────────────────────────────────────────────── */
function showTooltip(event, bar) {
  let tip = document.getElementById('forecast-tooltip');
  if (!tip) {
    tip = document.createElement('div');
    tip.id = 'forecast-tooltip';
    tip.style.cssText = [
      'position:fixed', 'padding:6px 10px', 'border-radius:4px',
      'background:#1f2937', 'color:#f9fafb', 'font-size:12px',
      'pointer-events:none', 'z-index:9999', 'white-space:nowrap',
    ].join(';');
    document.body.appendChild(tip);
  }
  const lines = [`<b>${bar.label}</b>`, `Due: ${bar.count}`];
  if (bar.count > 0 && !bar.is_overdue) {
    lines.push(`Avg mastery: ${bar.avg_mastery}`);
  }
  tip.innerHTML = lines.join('<br>');
  tip.style.left = `${event.clientX + 12}px`;
  tip.style.top  = `${event.clientY - 32}px`;
  tip.style.display = 'block';
}

function hideTooltip() {
  const tip = document.getElementById('forecast-tooltip');
  if (tip) tip.style.display = 'none';
}

/* ── Concept detail panel ───────────────────────────────────────────────── */
async function loadBucketConcepts(range, bucketKey, bucketLabel) {
  const card   = document.getElementById('forecast-concepts-card');
  const header = document.getElementById('forecast-concepts-header');
  const panel  = document.getElementById('forecast-concepts');

  card.style.display = 'block';
  header.textContent = `Concepts due — ${bucketLabel}`;
  panel.textContent  = 'Loading…';

  try {
    const url = `/api/forecast/concepts?range=${encodeURIComponent(range)}&bucket=${encodeURIComponent(bucketKey)}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const concepts = await res.json();
    renderConceptTable(concepts, panel);
  } catch (err) {
    panel.textContent = `Error: ${err.message}`;
  }
}

function renderConceptTable(concepts, panelEl) {
  if (!concepts.length) {
    panelEl.innerHTML = '<div style="color:var(--text2);font-size:13px">No concepts in this bucket.</div>';
    return;
  }

  const rows = concepts.map(c => {
    const m    = c.mastery_level ?? 0;
    const next = c.next_review_at ? c.next_review_at.slice(0, 10) : '—';
    const intv = c.interval_days  != null ? `${c.interval_days}d` : '—';
    const clr  = masteryColor(m);
    const bar  = `<div style="display:inline-block;width:${Math.round(m)}px;max-width:100px;height:8px;border-radius:4px;background:${clr}"></div>`;
    return `<tr>
      <td><a href="/concept/${c.id}">${escHtml(c.title)}</a></td>
      <td style="white-space:nowrap">${bar} <span style="font-size:12px;color:var(--text2)">${m}</span></td>
      <td>${next}</td>
      <td>${intv}</td>
    </tr>`;
  }).join('');

  panelEl.innerHTML = `
    <table>
      <thead><tr>
        <th>Concept</th>
        <th>Mastery</th>
        <th>Next review</th>
        <th>Interval</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function hideConcepts() {
  document.getElementById('forecast-concepts-card').style.display = 'none';
}

/* ── Utilities ─────────────────────────────────────────────────────────── */
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
