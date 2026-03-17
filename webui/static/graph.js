/**
 * Knowledge Graph Visualization — Learning Agent
 *
 * Architecture: data layer (pure functions, portable) + render layer (D3/DOM).
 * Reads window.__GRAPH_DATA injected by server.py.
 *
 * D3 v7 force-directed layout with:
 *  - Concept nodes (circles, 4-bucket mastery colors)
 *  - Topic nodes (rounded rects, accent blue)
 *  - Concept↔concept relation edges (muted by default, colored on hover)
 *  - Concept→topic membership edges (dashed, light)
 *  - Zoom/pan, drag, search, filters, layout toggle, legend
 */
;(function () {
  'use strict';

  const DATA = window.__GRAPH_DATA;
  if (!DATA) return;

  // ========================================================================
  // DATA LAYER — Pure functions (portable to mobile)
  // ========================================================================

  const MASTERY_TIERS = [
    { key: 'struggling', label: 'Struggling', min: 0,  max: 24, fill: '#ef4444', opacity: 0.6 },
    { key: 'building',   label: 'Building',   min: 25, max: 49, fill: '#f59e0b', opacity: 0.75 },
    { key: 'solid',      label: 'Solid',      min: 50, max: 74, fill: '#84cc16', opacity: 0.9 },
    { key: 'mastered',   label: 'Mastered',   min: 75, max: 100, fill: '#22c55e', opacity: 1.0 },
  ];

  const RELATION_COLORS = {
    builds_on:        { color: '#4CAF50', label: 'Builds on' },
    contrasts_with:   { color: '#FF9800', label: 'Contrasts with' },
    commonly_confused: { color: '#F44336', label: 'Commonly confused' },
    applied_together:  { color: '#2196F3', label: 'Applied together' },
    same_phenomenon:   { color: '#9C27B0', label: 'Same phenomenon' },
  };

  const TOPIC_COLOR = '#58a6ff';
  const CONCEPT_RADIUS = 8;
  const TOPIC_RADIUS = 14;

  function getMasteryTier(score) {
    const s = score || 0;
    for (const t of MASTERY_TIERS) {
      if (s >= t.min && s <= t.max) return t;
    }
    return MASTERY_TIERS[0];
  }

  function buildGraphModel(raw) {
    const nodes = [];
    const links = [];
    const conceptMap = new Map();
    const topicMap = new Map();

    // Topic nodes
    for (const t of raw.topic_nodes) {
      const node = {
        id: 'topic_' + t.id,
        rawId: t.id,
        type: 'topic',
        label: t.title,
        description: t.description,
      };
      nodes.push(node);
      topicMap.set(t.id, node);
    }

    // Concept nodes
    for (const c of raw.concept_nodes) {
      const tier = getMasteryTier(c.mastery_level);
      const node = {
        id: 'concept_' + c.id,
        rawId: c.id,
        type: 'concept',
        label: c.title,
        description: c.description || '',
        mastery: c.mastery_level || 0,
        tier: tier,
        reviewCount: c.review_count || 0,
        nextReview: c.next_review_at,
        intervalDays: c.interval_days,
        topicIds: c.topic_ids || [],
        topicNames: c.topic_names || '',
      };
      nodes.push(node);
      conceptMap.set(c.id, node);
    }

    // Concept↔concept relation edges
    for (const e of raw.concept_edges) {
      const src = conceptMap.get(e.concept_id_low);
      const tgt = conceptMap.get(e.concept_id_high);
      if (src && tgt) {
        links.push({
          source: src.id,
          target: tgt.id,
          edgeType: 'relation',
          relationType: e.relation_type,
          note: e.note,
        });
      }
    }

    // Concept→topic membership edges
    for (const e of raw.concept_topic_edges) {
      const cNode = conceptMap.get(e.concept_id);
      const tNode = topicMap.get(e.topic_id);
      if (cNode && tNode) {
        links.push({
          source: cNode.id,
          target: tNode.id,
          edgeType: 'membership',
        });
      }
    }

    // Topic→topic hierarchy edges
    for (const e of raw.topic_edges) {
      const p = topicMap.get(e.parent_id);
      const c = topicMap.get(e.child_id);
      if (p && c) {
        links.push({
          source: p.id,
          target: c.id,
          edgeType: 'hierarchy',
        });
      }
    }

    return { nodes, links, conceptMap, topicMap, raw };
  }

  function filterByTopic(model, topicId) {
    if (!topicId) return null; // no filter
    const linked = new Set();
    for (const l of model.links) {
      if (l.edgeType === 'membership') {
        const tId = typeof l.target === 'object' ? l.target.id : l.target;
        if (tId === 'topic_' + topicId) {
          const cId = typeof l.source === 'object' ? l.source.id : l.source;
          linked.add(cId);
        }
      }
    }
    return linked; // set of concept node IDs to show
  }

  function filterByMastery(tier) {
    if (!tier || tier === 'all') return null;
    const t = MASTERY_TIERS.find(m => m.key === tier);
    if (!t) return null;
    return t;
  }

  function searchNodes(model, query) {
    if (!query || query.length < 1) return null;
    const q = query.toLowerCase();
    const matched = new Set();
    for (const n of model.nodes) {
      if (n.label.toLowerCase().includes(q)) matched.add(n.id);
    }
    return matched;
  }

  // ========================================================================
  // RENDER LAYER — D3/DOM (web-only)
  // ========================================================================

  const container = document.getElementById('graph-container');
  const emptyEl = document.getElementById('graph-empty');
  const tooltipEl = document.getElementById('graph-tooltip');
  const legendEl = document.getElementById('graph-legend');

  // Build model
  const model = buildGraphModel(DATA);
  const conceptCount = model.nodes.filter(n => n.type === 'concept').length;
  const hasRelations = model.links.some(l => l.edgeType === 'relation');

  // Empty state
  if (conceptCount === 0) {
    emptyEl.style.display = 'block';
    container.querySelector('svg')?.remove();
    return;
  }

  // Small graph message
  if (conceptCount < 5 && conceptCount > 0) {
    const notice = document.createElement('div');
    notice.className = 'graph-cap-notice';
    notice.textContent = `Your knowledge graph is just getting started! Keep learning to see it grow. (${conceptCount} concept${conceptCount > 1 ? 's' : ''})`;
    container.parentNode.insertBefore(notice, container);
  }

  // ── SVG setup ──────────────────────────────────────────────────────────

  const width = container.clientWidth || window.innerWidth;
  const height = container.clientHeight || (window.innerHeight - 110);

  const svg = d3.select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height);

  const g = svg.append('g'); // master group for zoom

  // Zoom behavior
  const zoom = d3.zoom()
    .scaleExtent([0.1, 5])
    .on('zoom', (event) => g.attr('transform', event.transform));
  svg.call(zoom);

  // ── Force simulation ───────────────────────────────────────────────────

  let currentLayout = 'force'; // 'force' or 'cluster'

  const simulation = d3.forceSimulation(model.nodes)
    .force('link', d3.forceLink(model.links).id(d => d.id).distance(d => {
      if (d.edgeType === 'relation') return 80;
      if (d.edgeType === 'membership') return 120;
      return 100; // hierarchy
    }))
    .force('charge', d3.forceManyBody().strength(d => d.type === 'topic' ? -300 : -120))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collision', d3.forceCollide().radius(d => d.type === 'topic' ? TOPIC_RADIUS + 6 : CONCEPT_RADIUS + 4))
    .alphaDecay(0.02);

  // ── Draw edges ─────────────────────────────────────────────────────────

  const linkG = g.append('g').attr('class', 'links');

  const linkElements = linkG.selectAll('line')
    .data(model.links)
    .join('line')
    .attr('class', d => {
      let cls = 'graph-edge';
      if (d.edgeType === 'membership') cls += ' membership';
      if (d.edgeType === 'hierarchy') cls += ' membership';
      return cls;
    })
    .attr('stroke', d => (d.edgeType === 'membership' || d.edgeType === 'hierarchy') ? '#58a6ff' : '#c9d1d9')
    .attr('stroke-opacity', d => (d.edgeType === 'membership' || d.edgeType === 'hierarchy') ? 0.45 : 0.6)
    .attr('stroke-width', d => d.edgeType === 'relation' ? 2 : 1.5)
    .attr('stroke-dasharray', d => (d.edgeType === 'membership' || d.edgeType === 'hierarchy') ? '6 3' : null);

  // ── Draw nodes ─────────────────────────────────────────────────────────

  const nodeG = g.append('g').attr('class', 'nodes');

  const nodeElements = nodeG.selectAll('g')
    .data(model.nodes)
    .join('g')
    .attr('class', d => 'node node-' + d.type)
    .style('cursor', 'pointer')
    .call(d3.drag()
      .on('start', dragStarted)
      .on('drag', dragged)
      .on('end', dragEnded));

  // Concept nodes — circles
  nodeElements.filter(d => d.type === 'concept')
    .append('circle')
    .attr('r', CONCEPT_RADIUS)
    .attr('fill', d => d.tier.fill)
    .attr('fill-opacity', d => d.tier.opacity)
    .attr('stroke', '#fff')
    .attr('stroke-width', 0.5)
    .attr('stroke-opacity', 0.3);

  // Topic nodes — larger circles (using circles instead of rects for force layout stability)
  nodeElements.filter(d => d.type === 'topic')
    .append('circle')
    .attr('r', TOPIC_RADIUS)
    .attr('fill', TOPIC_COLOR)
    .attr('fill-opacity', 0.85)
    .attr('stroke', '#fff')
    .attr('stroke-width', 1)
    .attr('stroke-opacity', 0.4);

  // Topic labels
  nodeElements.filter(d => d.type === 'topic')
    .append('text')
    .attr('dy', TOPIC_RADIUS + 14)
    .attr('text-anchor', 'middle')
    .attr('fill', '#e6edf3')
    .attr('font-size', '11px')
    .attr('font-weight', '600')
    .attr('pointer-events', 'none')
    .text(d => d.label.length > 20 ? d.label.slice(0, 18) + '…' : d.label);

  // Concept labels (only show if few nodes)
  if (conceptCount <= 30) {
    nodeElements.filter(d => d.type === 'concept')
      .append('text')
      .attr('dy', CONCEPT_RADIUS + 12)
      .attr('text-anchor', 'middle')
      .attr('fill', '#8b949e')
      .attr('font-size', '10px')
      .attr('pointer-events', 'none')
      .text(d => d.label.length > 22 ? d.label.slice(0, 20) + '…' : d.label);
  }

  // ── Click behavior (navigate) ──────────────────────────────────────────

  nodeElements.on('click', (event, d) => {
    if (event.defaultPrevented) return; // drag
    if (d.type === 'concept') window.location.href = '/concept/' + d.rawId;
    if (d.type === 'topic') window.location.href = '/topic/' + d.rawId;
  });

  // ── Hover: tooltip + edge colorization ─────────────────────────────────

  nodeElements.on('mouseenter', (event, d) => {
    // Colorize connected edges
    linkElements
      .classed('edge-dimmed', true)
      .each(function (l) {
        const srcId = typeof l.source === 'object' ? l.source.id : l.source;
        const tgtId = typeof l.target === 'object' ? l.target.id : l.target;
        if (srcId === d.id || tgtId === d.id) {
          const el = d3.select(this);
          el.classed('edge-dimmed', false);
          if (l.edgeType === 'relation' && l.relationType) {
            el.classed('graph-edge edge-' + l.relationType, true);
            el.attr('stroke-width', 2.5);
          }
        }
      });

    // Show tooltip
    showTooltip(event, d);
  });

  nodeElements.on('mouseleave', () => {
    // Reset edges
    linkElements
      .classed('edge-dimmed', false)
      .attr('class', d => {
        let cls = 'graph-edge';
        if (d.edgeType === 'membership' || d.edgeType === 'hierarchy') cls += ' membership';
        return cls;
      })
      .attr('stroke', d => (d.edgeType === 'membership' || d.edgeType === 'hierarchy') ? '#58a6ff' : '#c9d1d9')
      .attr('stroke-opacity', d => (d.edgeType === 'membership' || d.edgeType === 'hierarchy') ? 0.45 : 0.6)
      .attr('stroke-width', d => d.edgeType === 'relation' ? 2 : 1.5)
      .attr('stroke-dasharray', d => (d.edgeType === 'membership' || d.edgeType === 'hierarchy') ? '6 3' : null);

    hideTooltip();
  });

  // Tooltip for edges
  linkElements.on('mouseenter', (event, d) => {
    if (d.edgeType !== 'relation') return;
    const info = RELATION_COLORS[d.relationType] || { label: d.relationType };
    let html = `<div class="tt-title">${info.label}</div>`;
    if (d.note) html += `<div class="tt-meta">${d.note}</div>`;
    tooltipEl.innerHTML = html;
    tooltipEl.style.display = 'block';
    positionTooltip(event);
  });
  linkElements.on('mouseleave', hideTooltip);

  function showTooltip(event, d) {
    let html = '';
    if (d.type === 'concept') {
      const tier = d.tier;
      const scoreWidth = Math.max(0, Math.min(100, d.mastery));
      const scoreCls = d.mastery >= 75 ? 'filled' : d.mastery >= 50 ? 'filled' : d.mastery >= 25 ? 'mid' : 'low';
      html += `<div class="tt-title">${escHtml(d.label)}</div>`;
      html += `<div class="tt-score">Score: <span class="mastery-bar"><span class="score-fill ${scoreCls}" style="width:${scoreWidth}%"></span><span class="score-label">${d.mastery}</span></span></div>`;
      // Due info
      if (d.nextReview) {
        const now = new Date();
        const nr = new Date(d.nextReview.replace(' ', 'T'));
        const diffH = (nr - now) / 3600000;
        let dueStr = '';
        if (diffH <= 0) dueStr = '<span style="color:var(--red)">Due now</span>';
        else if (diffH < 24) dueStr = 'Due in ' + Math.round(diffH) + 'h';
        else dueStr = 'Due in ' + Math.round(diffH / 24) + 'd';
        html += `<div class="tt-meta">${dueStr} · ${d.intervalDays || 1}d interval · ${d.reviewCount} reviews</div>`;
      }
      if (d.topicNames) {
        html += `<div class="tt-meta">Topics: ${escHtml(d.topicNames)}</div>`;
      }
      if (d.description) {
        const desc = d.description.length > 80 ? d.description.slice(0, 78) + '…' : d.description;
        html += `<div class="tt-remark">${escHtml(desc)}</div>`;
      }
    } else {
      html += `<div class="tt-title">${escHtml(d.label)}</div>`;
      html += `<div class="tt-meta">Topic</div>`;
      if (d.description) html += `<div class="tt-remark">${escHtml(d.description)}</div>`;
    }
    tooltipEl.innerHTML = html;
    tooltipEl.style.display = 'block';
    positionTooltip(event);
  }

  function positionTooltip(event) {
    const rect = container.getBoundingClientRect();
    let x = event.clientX - rect.left + 14;
    let y = event.clientY - rect.top - 10;
    // Keep within bounds
    if (x + 300 > rect.width) x = x - 320;
    if (y + 200 > rect.height) y = y - 100;
    tooltipEl.style.left = x + 'px';
    tooltipEl.style.top = y + 'px';
  }

  function hideTooltip() {
    tooltipEl.style.display = 'none';
  }

  function escHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  // ── Simulation tick ────────────────────────────────────────────────────

  simulation.on('tick', () => {
    linkElements
      .attr('x1', d => d.source.x)
      .attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x)
      .attr('y2', d => d.target.y);

    nodeElements.attr('transform', d => `translate(${d.x},${d.y})`);
  });

  // ── Drag handlers ──────────────────────────────────────────────────────

  function dragStarted(event, d) {
    if (!event.active) simulation.alphaTarget(0.3).restart();
    d.fx = d.x;
    d.fy = d.y;
  }

  function dragged(event, d) {
    d.fx = event.x;
    d.fy = event.y;
  }

  function dragEnded(event, d) {
    if (!event.active) simulation.alphaTarget(0);
    d.fx = null;
    d.fy = null;
  }

  // ========================================================================
  // CONTROLS
  // ========================================================================

  // ── Populate topic dropdown ────────────────────────────────────────────

  const topicDropdown = document.getElementById('graph-topic-filter');
  const topicsSorted = [...DATA.topic_nodes].sort((a, b) => a.title.localeCompare(b.title));
  for (const t of topicsSorted) {
    const opt = document.createElement('option');
    opt.value = t.id;
    opt.textContent = t.title;
    topicDropdown.appendChild(opt);
  }

  // ── Active filters state ───────────────────────────────────────────────

  let activeTopicFilter = null;
  let activeMasteryFilter = null;
  let activeSearchQuery = '';

  function applyFilters() {
    const topicSet = filterByTopic(model, activeTopicFilter);
    const masteryTier = filterByMastery(activeMasteryFilter);
    const searchSet = searchNodes(model, activeSearchQuery);

    const anyFilter = topicSet || masteryTier || searchSet;

    nodeElements.each(function (d) {
      const el = d3.select(this);
      let visible = true;

      if (d.type === 'concept') {
        if (topicSet && !topicSet.has(d.id)) visible = false;
        if (masteryTier && (d.mastery < masteryTier.min || d.mastery > masteryTier.max)) visible = false;
        if (searchSet && !searchSet.has(d.id)) visible = false;
      } else if (d.type === 'topic') {
        if (searchSet && !searchSet.has(d.id)) visible = false;
      }

      el.classed('node-dimmed', anyFilter && !visible);
      el.classed('node-match', anyFilter && visible && searchSet);
    });

    linkElements.each(function (l) {
      const el = d3.select(this);
      const srcId = typeof l.source === 'object' ? l.source.id : l.source;
      const tgtId = typeof l.target === 'object' ? l.target.id : l.target;

      const srcVisible = !nodeElements.filter(d => d.id === srcId).classed('node-dimmed');
      const tgtVisible = !nodeElements.filter(d => d.id === tgtId).classed('node-dimmed');

      el.classed('edge-dimmed', anyFilter && (!srcVisible || !tgtVisible));
    });
  }

  // ── Topic filter ───────────────────────────────────────────────────────

  topicDropdown.addEventListener('change', () => {
    activeTopicFilter = topicDropdown.value ? parseInt(topicDropdown.value) : null;
    applyFilters();
  });

  // ── Mastery filter (btn-group) ─────────────────────────────────────────

  const masteryBtns = document.querySelectorAll('#graph-mastery-filter .filter-btn');
  masteryBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      masteryBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeMasteryFilter = btn.dataset.mastery;
      applyFilters();
    });
  });

  // ── Search ─────────────────────────────────────────────────────────────

  const searchInput = document.getElementById('graph-search');
  const searchClear = document.getElementById('graph-search-clear');
  let searchTimeout;

  searchInput.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      activeSearchQuery = searchInput.value.trim();
      searchClear.style.display = activeSearchQuery ? 'block' : 'none';
      applyFilters();
    }, 200);
  });

  searchClear.addEventListener('click', () => {
    searchInput.value = '';
    activeSearchQuery = '';
    searchClear.style.display = 'none';
    applyFilters();
  });

  // ── Layout toggle ──────────────────────────────────────────────────────

  const layoutBtns = document.querySelectorAll('#graph-layout-toggle .filter-btn');
  layoutBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      layoutBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      switchLayout(btn.dataset.layout);
    });
  });

  function switchLayout(mode) {
    currentLayout = mode;
    simulation.stop();

    if (mode === 'cluster') {
      // Compute topic cluster positions (arrange in a circle)
      const topicNodes = model.nodes.filter(n => n.type === 'topic');
      const clusterPositions = {};
      const angleStep = (2 * Math.PI) / (topicNodes.length || 1);
      const clusterRadius = Math.min(width, height) * 0.35;

      topicNodes.forEach((t, i) => {
        const angle = i * angleStep - Math.PI / 2;
        clusterPositions[t.id] = {
          x: width / 2 + clusterRadius * Math.cos(angle),
          y: height / 2 + clusterRadius * Math.sin(angle),
        };
      });

      simulation
        .force('center', null)
        .force('x', d3.forceX(d => {
          if (d.type === 'topic') return clusterPositions[d.id]?.x || width / 2;
          // Concept → position near its first topic
          if (d.topicIds && d.topicIds.length > 0) {
            const tId = 'topic_' + d.topicIds[0];
            return clusterPositions[tId]?.x || width / 2;
          }
          return width / 2;
        }).strength(0.6))
        .force('y', d3.forceY(d => {
          if (d.type === 'topic') return clusterPositions[d.id]?.y || height / 2;
          if (d.topicIds && d.topicIds.length > 0) {
            const tId = 'topic_' + d.topicIds[0];
            return clusterPositions[tId]?.y || height / 2;
          }
          return height / 2;
        }).strength(0.6))
        .alpha(0.8)
        .restart();
    } else {
      // Free layout — restore center force
      simulation
        .force('x', null)
        .force('y', null)
        .force('center', d3.forceCenter(width / 2, height / 2))
        .alpha(0.8)
        .restart();
    }
  }

  // ── Legend ──────────────────────────────────────────────────────────────

  const legendToggle = document.getElementById('graph-legend-toggle');
  legendToggle.addEventListener('click', () => {
    legendEl.classList.toggle('collapsed');
  });

  function buildLegend() {
    let html = '<h4>Mastery</h4>';
    for (const t of MASTERY_TIERS) {
      html += `<div class="legend-item"><span class="legend-swatch" style="background:${t.fill};opacity:${t.opacity}"></span>${t.label} (${t.min}–${t.max})</div>`;
    }
    html += `<div class="legend-item"><span class="legend-swatch" style="background:${TOPIC_COLOR}"></span>Topic</div>`;

    if (hasRelations) {
      html += '<h4>Relations</h4>';
      for (const [type, info] of Object.entries(RELATION_COLORS)) {
        html += `<div class="legend-item"><span class="legend-line" style="background:${info.color}"></span>${info.label}</div>`;
      }
      html += '<div class="legend-item" style="color:var(--text2);font-size:11px;margin-top:4px">Hover a node to reveal its relations</div>';
    }

    legendEl.innerHTML = html;
  }
  buildLegend();

  // ── Window resize ──────────────────────────────────────────────────────

  let resizeTimeout;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(() => {
      const w = container.clientWidth;
      const h = container.clientHeight;
      svg.attr('width', w).attr('height', h);
      if (currentLayout === 'force') {
        simulation.force('center', d3.forceCenter(w / 2, h / 2));
      }
      simulation.alpha(0.3).restart();
    }, 200);
  });

  // ── Auto-zoom to fit on initial load ───────────────────────────────────

  simulation.on('end', function initialFit() {
    simulation.on('end', null); // run once
    zoomToFit();
  });

  // Also fit after a short delay if simulation is still running
  setTimeout(zoomToFit, 3000);

  function zoomToFit() {
    const bounds = g.node().getBBox();
    if (bounds.width === 0 || bounds.height === 0) return;

    const pad = 40;
    const fullWidth = svg.attr('width');
    const fullHeight = svg.attr('height');
    const scale = Math.min(
      (fullWidth - pad * 2) / bounds.width,
      (fullHeight - pad * 2) / bounds.height,
      1.5 // don't zoom in too much
    );
    const tx = fullWidth / 2 - (bounds.x + bounds.width / 2) * scale;
    const ty = fullHeight / 2 - (bounds.y + bounds.height / 2) * scale;

    svg.transition().duration(750).call(
      zoom.transform,
      d3.zoomIdentity.translate(tx, ty).scale(scale)
    );
  }

})();
