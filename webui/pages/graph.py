"""Knowledge graph visualization page."""

import json

import config
import db
from webui.helpers import layout


def page_graph() -> str:
    """Knowledge graph visualization page. Full-bleed layout."""
    concepts = db.get_all_concepts_summary()
    topics = db.get_all_topics()
    relations = db.get_all_relations()
    topic_rels = db.get_topic_relations()
    ct_edges = db.get_concept_topic_edges()

    # Cap nodes for performance
    total_concepts = len(concepts)
    max_nodes = config.MAX_GRAPH_NODES
    if len(concepts) > max_nodes:
        concepts = sorted(concepts, key=lambda c: c.get('mastery_level') or 0, reverse=True)[:max_nodes]

    concept_ids = {c['id'] for c in concepts}
    relations = [e for e in relations if e['concept_id_low'] in concept_ids and e['concept_id_high'] in concept_ids]
    ct_edges = [e for e in ct_edges if e['concept_id'] in concept_ids]

    graph_data = {
        "concept_nodes": concepts,
        "topic_nodes": topics,
        "concept_edges": relations,
        "topic_edges": topic_rels,
        "concept_topic_edges": ct_edges,
        "total_concepts": total_concepts,
        "max_nodes": max_nodes,
    }

    data_script = f"""<script>
window.__GRAPH_DATA = {json.dumps(graph_data, default=str)};
</script>"""

    body = f"""{data_script}
    <div class="graph-controls">
      <div class="toolbar-search">
        <input type="text" id="graph-search" placeholder="Search nodes\u2026" autocomplete="off">
        <button class="search-clear" id="graph-search-clear" title="Clear search">\u2715</button>
      </div>
      <select id="graph-topic-filter">
        <option value="">All Topics</option>
      </select>
      <div class="filter-btn-group" id="graph-mastery-filter">
        <button class="filter-btn active" data-mastery="all">All</button>
        <button class="filter-btn" data-mastery="struggling">🔴 Struggling</button>
        <button class="filter-btn" data-mastery="building">🟡 Building</button>
        <button class="filter-btn" data-mastery="solid">🟢 Solid</button>
        <button class="filter-btn" data-mastery="mastered">\u2705 Mastered</button>
      </div>
      <div class="filter-btn-group" id="graph-layout-toggle">
        <button class="filter-btn active" data-layout="force">Free Layout</button>
        <button class="filter-btn" data-layout="cluster">Group by Topic</button>
      </div>
      <button class="btn btn-sm" id="graph-legend-toggle" title="Legend">\u24d8</button>
    </div>
    <div id="graph-container">
      <div id="graph-empty" class="empty" style="display:none">
        No concepts yet. Start learning to build your knowledge graph!
      </div>
      <div id="graph-legend" class="graph-legend collapsed">
      </div>
      <div id="graph-tooltip" class="graph-tooltip" style="display:none"></div>
    </div>
    <div id="graph-mobile-fallback" class="empty" style="display:none">
      The knowledge graph works best on a larger screen.<br>
      View your <a href="/topics">Topics</a> or <a href="/concepts">Concepts</a> instead.
    </div>
    """
    cap_notice = ""
    if total_concepts > max_nodes:
        cap_notice = f'<div class="graph-cap-notice">Showing top {max_nodes} of {total_concepts} concepts by mastery. Use filters to explore more.</div>'
        body = cap_notice + body

    return layout("Graph", body, active="graph",
                  extra_scripts='<script src="https://d3js.org/d3.v7.min.js"></script>\n<script src="/static/graph.js?v=3"></script>',
                  body_class="graph-page")
