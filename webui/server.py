#!/usr/bin/env python3
"""
Learning Agent — Database Web UI
A zero-dependency web interface for browsing and managing the knowledge DB.
Run:  python -m webui.server     (from learning_agent/)
  or: python webui/server.py     (from learning_agent/)
"""

import json
import mimetypes
import signal
import sys
import os
import threading
import urllib.parse
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Add project root (learning_agent/) to path so we can import db
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
import db

PORT = 8050
STATIC_DIR = Path(__file__).parent / "static"

# ============================================================================
# Helpers
# ============================================================================

def score_bar(score: int) -> str:
    """Inline score bar for concepts (0-100 scale)."""
    score = max(0, min(100, int(score)))
    if score >= 75:
        cls = "filled"
    elif score >= 50:
        cls = "filled"
    elif score >= 25:
        cls = "mid"
    else:
        cls = "low"
    return f'<span class="mastery-bar"><span class="score-fill {cls}" style="width:{score}%"></span><span class="score-label">{score}</span></span>'


def mastery_progress_bar(avg_score: float) -> str:
    """Small inline progress bar for average score (0-100 scale)."""
    pct = max(0, min(100, avg_score))
    if avg_score >= 50:
        cls = "high"
    elif avg_score >= 25:
        cls = "mid"
    else:
        cls = "low"
    return f'<span class="mastery-progress"><span class="fill {cls}" style="width:{pct:.0f}%"></span></span>'


def layout(title: str, body: str, active: str = "", extra_scripts: str = "", body_class: str = "") -> str:
    nav_items = [
        ("", "Dashboard"),
        ("topics", "Topics"),
        ("concepts", "Concepts"),
        ("graph", "Graph"),
        ("reviews", "Reviews"),
        ("actions", "Activity"),
    ]
    nav_html = ""
    for href, label in nav_items:
        cls = ' class="active"' if active == href else ""
        nav_html += f'<a href="/{href}"{cls}>{label}</a>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Learning Agent</title>
<link rel="stylesheet" href="/static/style.css?v=2">
</head>
<body>
<div class="container{' graph-page' if body_class else ''}">
<nav class="nav">
  <span class="brand">📚 Learning Agent</span>
  {nav_html}
</nav>
{body}
</div>
{extra_scripts}
</body>
</html>"""


# ============================================================================
# Tree rendering (shared between dashboard and topics page)
# ============================================================================

def compute_subtree_stats(topic_map):
    """Compute aggregated subtree stats for every topic via post-order DFS.

    Returns dict[topic_id] = {total_concepts, total_due, subtree_avg_mastery, subtopic_count}
    """
    by_id = {t['id']: t for t in topic_map}
    stats = {}  # topic_id -> {total_concepts, total_due, weighted_mastery_sum, subtopic_count}
    visited = set()

    def dfs(tid):
        if tid in visited:
            return stats.get(tid, {'total_concepts': 0, 'total_due': 0, 'weighted_mastery_sum': 0, 'subtopic_count': 0})
        visited.add(tid)
        t = by_id.get(tid)
        if not t:
            return {'total_concepts': 0, 'total_due': 0, 'weighted_mastery_sum': 0, 'subtopic_count': 0}

        own_concepts = t['concept_count']
        own_due = t['due_count']
        own_mastery_sum = t['avg_mastery'] * own_concepts if own_concepts > 0 else 0

        total_concepts = own_concepts
        total_due = own_due
        mastery_sum = own_mastery_sum
        subtopic_count = 0

        for cid in t.get('child_ids', []):
            child_stats = dfs(cid)
            total_concepts += child_stats['total_concepts']
            total_due += child_stats['total_due']
            mastery_sum += child_stats['weighted_mastery_sum']
            subtopic_count += 1 + child_stats['subtopic_count']

        s = {
            'total_concepts': total_concepts,
            'total_due': total_due,
            'weighted_mastery_sum': mastery_sum,
            'subtopic_count': subtopic_count,
        }
        stats[tid] = s
        return s

    for t in topic_map:
        dfs(t['id'])

    # Compute avg mastery from weighted sum
    result = {}
    for tid, s in stats.items():
        avg = (s['weighted_mastery_sum'] / s['total_concepts']) if s['total_concepts'] > 0 else 0
        result[tid] = {
            'total_concepts': s['total_concepts'],
            'total_due': s['total_due'],
            'subtree_avg_mastery': round(avg, 1),
            'subtopic_count': s['subtopic_count'],
        }
    return result


def render_tree_node(topic, by_id, subtree_stats, depth=0, expanded_default=True):
    """Render a single tree node with children as nested divs."""
    tid = topic['id']
    has_children = bool(topic.get('child_ids'))
    ss = subtree_stats.get(tid, {})

    # Chevron or placeholder
    if has_children:
        chevron = '<span class="chevron">▶</span>'
    else:
        chevron = '<span class="chevron-placeholder"></span>'

    # Stats pills
    own_count = topic['concept_count']
    total_count = ss.get('total_concepts', own_count)
    own_due = topic['due_count']
    total_due = ss.get('total_due', own_due)
    avg_mastery = topic['avg_mastery']
    subtree_mastery = ss.get('subtree_avg_mastery', avg_mastery)

    # Concept count pill — show "own / total" if subtree is bigger
    if has_children and total_count != own_count:
        count_text = f'{own_count} / {total_count}'
    else:
        count_text = str(own_count)

    # Due badge
    due_html = ""
    if total_due > 0:
        due_text = f'{total_due} due' if total_due == own_due or not has_children else f'{own_due}/{total_due} due'
        due_html = f'<span class="stat-pill has-due">{due_text}</span>'

    # Mastery — use subtree mastery if node has children
    display_mastery = subtree_mastery if has_children else avg_mastery
    mastery_html = mastery_progress_bar(display_mastery)

    # Node state
    if has_children:
        state_cls = "expanded" if expanded_default else "collapsed"
    else:
        state_cls = ""

    title_escaped = topic['title'].replace('"', '&quot;').replace('<', '&lt;')

    html = f'<div class="tree-node {state_cls}" data-id="{tid}" data-title="{title_escaped}">'
    html += f'<div class="tree-node-header">'
    html += chevron
    html += f'<span class="node-title"><a href="/topic/{tid}">{topic["title"]}</a></span>'
    html += f'<span class="node-stats">'
    html += f'<span class="stat-pill">{count_text} concepts</span>'
    html += f'{mastery_html}'
    html += due_html
    html += f'</span>'
    html += f'</div>'

    # Children
    if has_children:
        html += '<div class="tree-node-children">'
        for cid in topic['child_ids']:
            child = by_id.get(cid)
            if child:
                html += render_tree_node(child, by_id, subtree_stats, depth + 1, expanded_default=False)
        html += '</div>'

    html += '</div>'
    return html


def build_breadcrumb(topic_id, by_id_full=None):
    """Build a breadcrumb trail from root to the given topic."""
    if by_id_full is None:
        return ""

    # Walk up to root(s) — pick the first parent chain
    chain = []
    seen = set()
    current = topic_id
    while current and current not in seen:
        seen.add(current)
        t = by_id_full.get(current)
        if not t:
            break
        chain.append(t)
        parents = t.get('parent_ids', [])
        current = parents[0] if parents else None

    chain.reverse()

    if len(chain) <= 1:
        return ""

    parts = []
    for i, t in enumerate(chain):
        if i < len(chain) - 1:
            parts.append(f'<a href="/topic/{t["id"]}">{t["title"]}</a>')
        else:
            parts.append(f'<span style="color:var(--text)">{t["title"]}</span>')

    sep = '<span class="sep">›</span>'
    return f'<div class="breadcrumb"><a href="/topics">Topics</a>{sep}{sep.join(parts)}</div>'


# ============================================================================
# Pages
# ============================================================================

def page_dashboard() -> str:
    stats = db.get_review_stats()
    topic_map = db.get_topic_map()

    stats_html = f"""
    <div class="stats">
      <div class="stat"><div class="num">{stats['total_concepts']}</div><div class="label">Concepts</div></div>
      <div class="stat"><div class="num">{len(topic_map)}</div><div class="label">Topics</div></div>
      <div class="stat"><div class="num">{stats['due_now']}</div><div class="label">Due Now</div></div>
      <div class="stat"><div class="num">{stats['reviews_last_7d']}</div><div class="label">Reviews (7d)</div></div>
      <div class="stat"><div class="num">{stats['avg_mastery']}/100</div><div class="label">Avg Score</div></div>
    </div>"""

    # Due concepts
    due = db.get_due_concepts(limit=10)
    if due:
        due_rows = ""
        for c in due:
            due_rows += f"""<tr>
              <td><a href="/concept/{c['id']}">{c['title']}</a></td>
              <td>{score_bar(c['mastery_level'])}</td>
              <td>{c['next_review_at'] or '—'}</td>
            </tr>"""
        due_html = f"""
        <div class="card">
          <h3>⏰ Due for Review</h3>
          <table><thead><tr><th>Concept</th><th>Score</th><th>Due</th></tr></thead>
          <tbody>{due_rows}</tbody></table>
        </div>"""
    else:
        due_html = '<div class="card"><p>No concepts due for review right now.</p></div>'

    # Topic tree (compact — roots collapsed by default)
    if topic_map:
        roots = [t for t in topic_map if not t['parent_ids']]
        by_id = {t['id']: t for t in topic_map}
        subtree_stats = compute_subtree_stats(topic_map)

        tree_html = '<div class="topic-tree">'
        for r in sorted(roots, key=lambda x: x['title']):
            tree_html += render_tree_node(r, by_id, subtree_stats, expanded_default=True)

        # Orphans
        shown_ids = set()
        def collect_ids(t):
            shown_ids.add(t['id'])
            for cid in t.get('child_ids', []):
                c = by_id.get(cid)
                if c:
                    collect_ids(c)
        for r in roots:
            collect_ids(r)
        orphans = [t for t in topic_map if t['id'] not in shown_ids]
        for o in orphans:
            tree_html += render_tree_node(o, by_id, subtree_stats, expanded_default=False)

        tree_html += '</div>'
        topic_html = f'<div class="card"><h3>🗂 Topics</h3>{tree_html}</div>'
    else:
        topic_html = '<div class="card"><p>No topics yet. Start learning via the Discord bot!</p></div>'

    # Recent activity summary card
    try:
        activity = db.get_action_summary(days=7)
        today_total = activity.get('today_total', 0)
        week_total = activity.get('total', 0)
        today_actions = activity.get('today_by_action', {})
        week_actions = activity.get('by_action', {})

        def _summarize(d):
            parts = []
            for key, label in [('assess', 'reviews'), ('add_concept', 'concepts added'),
                               ('add_topic', 'topics created'), ('quiz', 'quizzes')]:
                if d.get(key):
                    parts.append(f"{d[key]} {label}")
            return ', '.join(parts) if parts else 'no activity'

        activity_html = f'''<div class="card">
          <h3>📋 Recent Activity</h3>
          <p style="font-size:14px;margin:6px 0">Today: {_summarize(today_actions)} ({today_total} total)</p>
          <p style="font-size:14px;margin:6px 0;color:var(--text2)">This week: {_summarize(week_actions)} ({week_total} total)</p>
          <p style="margin-top:10px"><a href="/actions">View full activity log →</a></p>
        </div>'''
    except Exception:
        activity_html = ''

    return layout("Dashboard", stats_html + due_html + activity_html + topic_html, active="",
                   extra_scripts='<script src="/static/tree.js"></script>')


def page_topics() -> str:
    topics = db.get_all_topics()
    if not topics:
        body = '<div class="empty">No topics yet.</div>'
        return layout("Topics", body, active="topics")

    topic_map = db.get_topic_map()
    by_id = {t['id']: t for t in topic_map}
    subtree_stats = compute_subtree_stats(topic_map)

    roots = [t for t in topic_map if not t['parent_ids']]

    # Toolbar
    toolbar = f"""
    <div class="tree-toolbar">
      <input type="text" id="tree-search" placeholder="Search topics..." autocomplete="off">
      <span id="tree-match-count" class="match-count"></span>
      <button class="btn btn-sm btn-primary" id="tree-expand-all">Expand All</button>
      <button class="btn btn-sm" id="tree-collapse-all" style="background:var(--surface);color:var(--text);border:1px solid var(--border)">Collapse All</button>
    </div>"""

    # Build tree
    tree_html = '<div class="topic-tree">'
    for r in sorted(roots, key=lambda x: x['title']):
        tree_html += render_tree_node(r, by_id, subtree_stats, expanded_default=True)

    # Orphans
    shown_ids = set()
    def collect_ids(t):
        shown_ids.add(t['id'])
        for cid in t.get('child_ids', []):
            c = by_id.get(cid)
            if c:
                collect_ids(c)
    for r in roots:
        collect_ids(r)
    orphans = [t for t in topic_map if t['id'] not in shown_ids]
    if orphans:
        tree_html += '<div class="orphan-section"><h4>⚠ Uncategorized (no parent)</h4>'
        for o in sorted(orphans, key=lambda x: x['title']):
            tree_html += render_tree_node(o, by_id, subtree_stats, expanded_default=False)
        tree_html += '</div>'

    tree_html += '</div>'

    # Summary stats
    total_topics = len(topic_map)
    root_count = len(roots)
    orphan_count = len(orphans)
    summary = f'{total_topics} topics ({root_count} root'
    if orphan_count:
        summary += f', {orphan_count} uncategorized'
    summary += ')'

    body = f"""
    <h2 style="margin-bottom:4px">Topics</h2>
    <p style="color:var(--text2);font-size:13px;margin-bottom:16px">{summary}</p>
    {toolbar}
    {tree_html}"""

    return layout("Topics", body, active="topics",
                   extra_scripts='<script src="/static/tree.js"></script>')


def page_topic_detail(topic_id: int) -> str:
    topic = db.get_topic(topic_id)
    if not topic:
        return layout("Not Found", '<div class="empty">Topic not found.</div>')

    concepts = db.get_concepts_for_topic(topic_id)
    parents = db.get_topic_parents(topic_id)
    children = db.get_topic_children(topic_id)

    # Build breadcrumb using the full topic map
    topic_map = db.get_topic_map()
    by_id_full = {t['id']: t for t in topic_map}
    breadcrumb_html = build_breadcrumb(topic_id, by_id_full)

    # Back link
    back_html = '<p><a href="/topics">← Topics</a></p>'

    # Parent/child links (legacy text links for parents)
    rel_html = ""
    if parents:
        parent_links = ", ".join(f'<a href="/topic/{p["id"]}">{p["title"]}</a>' for p in parents)
        rel_html += f'<p style="font-size:13px;color:var(--text2)">Parent(s): {parent_links}</p>'

    # Children as cards instead of plain links
    if children:
        # Get stats for children
        subtree_stats = compute_subtree_stats(topic_map)
        child_cards = '<div class="child-topics">'
        for c in children:
            ss = subtree_stats.get(c['id'], {})
            child_tm = by_id_full.get(c['id'], {})
            own_count = child_tm.get('concept_count', 0)
            total = ss.get('total_concepts', own_count)
            avg_m = ss.get('subtree_avg_mastery', 0)
            count_str = f'{own_count} / {total} concepts' if total != own_count else f'{own_count} concepts'
            child_cards += f'''<a href="/topic/{c['id']}" class="child-topic-card">
              <div class="card-title">{c['title']}</div>
              <td>{mastery_progress_bar(avg_m)} <span style="font-size:12px;color:var(--text2)">{count_str} · score {avg_m}/100</span></td>
            </a>'''
        child_cards += '</div>'
        rel_html += f'<div class="section"><h4>Subtopics ({len(children)})</h4>{child_cards}</div>'

    # Concepts table
    if concepts:
        rows = ""
        for c in concepts:
            due = ""
            if c['next_review_at']:
                from datetime import datetime as dt
                try:
                    nr = dt.strptime(c['next_review_at'], '%Y-%m-%d %H:%M:%S')
                    if nr <= dt.now():
                        due = '<span class="badge due">DUE</span>'
                except:
                    pass
            remark = (c.get('latest_remark') or '')[:60]
            rows += f"""<tr>
              <td><a href="/concept/{c['id']}">#{c['id']}</a></td>
              <td><a href="/concept/{c['id']}">{c['title']}</a></td>
              <td>{score_bar(c['mastery_level'])}</td>
              <td>{c.get('interval_days', 1)}d</td>
              <td>{c['next_review_at'] or '—'} {due}</td>
              <td style="color:var(--text2);font-size:12px">{remark}</td>
            </tr>"""
        concept_html = f"""
        <table>
          <thead><tr><th>ID</th><th>Title</th><th>Score</th><th>Interval</th><th>Next Review</th><th>Latest Remark</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>"""
    else:
        concept_html = '<div class="empty">No concepts in this topic yet.</div>'

    body = f"""
    {back_html}
    {breadcrumb_html}
    <h2 style="margin:12px 0 4px">{topic['title']}</h2>
    <p style="color:var(--text2)">{topic.get('description') or ''}</p>
    {rel_html}
    <div class="section">
      <h4>Concepts ({len(concepts)})</h4>
      {concept_html}
    </div>"""
    return layout(topic['title'], body, active="topics")


def page_concepts() -> str:
    # Get all concepts with structured topic data
    concepts = db.get_all_concepts_with_topics()
    # Get flat topic list for the filter dropdown
    all_topics = db.get_all_topics()
    topic_list = [{'id': t['id'], 'title': t['title']} for t in all_topics]

    # Serialize for client-side JS
    # Strip heavy fields not needed for the table
    concepts_json = []
    for c in concepts:
        concepts_json.append({
            'id': c['id'],
            'title': c['title'],
            'mastery_level': c.get('mastery_level', 0),
            'interval_days': c.get('interval_days', 1),
            'review_count': c.get('review_count', 0),
            'next_review_at': c.get('next_review_at'),
            'last_reviewed_at': c.get('last_reviewed_at'),
            'latest_remark': c.get('latest_remark'),
            'topics': c.get('topics', []),
        })

    data_script = f"""<script>
window.__CONCEPTS = {json.dumps(concepts_json, default=str)};
window.__TOPICS = {json.dumps(topic_list, default=str)};
</script>"""

    body = f"""
    {data_script}
    <div class="concepts-header">
      <h2>All Concepts <span id="concepts-count" class="concepts-count-badge">({len(concepts_json)})</span></h2>
    </div>
    <div class="concepts-toolbar">
      <div class="toolbar-search">
        <input type="text" id="concept-search" placeholder="Search concepts…" autocomplete="off">
        <button class="search-clear" id="search-clear" title="Clear search">✕</button>
      </div>
      <select id="concept-topic-filter">
        <option value="">All Topics</option>
      </select>
      <div class="filter-btn-group" id="status-filter">
        <button class="filter-btn active" data-status="all">All</button>
        <button class="filter-btn" data-status="due">🔴 Due</button>
        <button class="filter-btn" data-status="upcoming">Upcoming</button>
        <button class="filter-btn" data-status="never">New</button>
      </div>
    </div>
    <table id="concepts-table">
      <thead><tr>
        <th class="sortable th-id" data-sort="id">ID</th>
        <th class="sortable" data-sort="title">Concept</th>
        <th>Topics</th>
        <th class="sortable th-score" data-sort="mastery_level">Score</th>
        <th class="sortable th-interval" data-sort="interval_days">Interval</th>
        <th class="sortable th-reviews" data-sort="review_count">Reviews</th>
        <th class="sortable" data-sort="next_review_at">Next Review</th>
        <th class="sortable th-last-review" data-sort="last_reviewed_at">Last Review</th>
        <th class="th-actions"></th>
      </tr></thead>
      <tbody id="concepts-body"></tbody>
    </table>
    <div id="concepts-empty" class="empty" style="display:none"></div>

    <!-- Delete confirmation modal -->
    <div id="delete-modal" class="modal-overlay" style="display:none">
      <div class="modal-card">
        <h3>⚠️ Delete Concept</h3>
        <p id="delete-modal-msg">Are you sure?</p>
        <div class="modal-actions">
          <button class="btn" id="delete-cancel">Cancel</button>
          <button class="btn btn-danger" id="delete-confirm">Delete</button>
        </div>
      </div>
    </div>

    <!-- Toast container -->
    <div id="toast-container"></div>
    """
    return layout("Concepts", body, active="concepts",
                   extra_scripts='<script src="/static/concepts.js?v=2"></script>')


def page_concept_detail(concept_id: int) -> str:
    detail = db.get_concept_detail(concept_id)
    if not detail:
        return layout("Not Found", '<div class="empty">Concept not found.</div>')

    # Topic tags
    tags = "".join(
        f'<a href="/topic/{t["id"]}" class="tag">{t["title"]}</a>'
        for t in detail.get('topics', [])
    ) or '<span style="color:var(--text2)">untagged</span>'

    # Score info
    due = ""
    if detail['next_review_at']:
        from datetime import datetime as dt
        try:
            nr = dt.strptime(detail['next_review_at'], '%Y-%m-%d %H:%M:%S')
            if nr <= dt.now():
                due = ' <span class="badge due">OVERDUE</span>'
            else:
                due = ' <span class="badge ok">upcoming</span>'
        except:
            pass

    info_html = f"""
    <div class="card">
      <table style="font-size:14px">
        <tr><td style="color:var(--text2);width:140px">Score</td><td>{score_bar(detail['mastery_level'])} ({detail['mastery_level']}/100)</td></tr>
        <tr><td style="color:var(--text2)">Interval</td><td>{detail.get('interval_days', 1)} days</td></tr>
        <tr><td style="color:var(--text2)">Next Review</td><td>{detail.get('next_review_at') or '—'}{due}</td></tr>
        <tr><td style="color:var(--text2)">Last Reviewed</td><td>{detail.get('last_reviewed_at') or 'never'}</td></tr>
        <tr><td style="color:var(--text2)">Review Count</td><td>{detail.get('review_count', 0)}</td></tr>
        <tr><td style="color:var(--text2)">Topics</td><td>{tags}</td></tr>
        <tr><td style="color:var(--text2)">Created</td><td>{detail.get('created_at', '—')}</td></tr>
      </table>
    </div>"""

    # Remarks
    remarks = detail.get('remarks', [])
    if remarks:
        remark_html = ""
        for r in remarks:
            remark_html += f"""<div class="remark">
              {r['content']}
              <div class="time">{r.get('created_at', '')}</div>
            </div>"""
    else:
        remark_html = '<p style="color:var(--text2);font-size:13px">No remarks yet.</p>'

    # Reviews
    reviews = detail.get('recent_reviews', [])
    if reviews:
        review_html = ""
        for rv in reviews:
            q_colors = {0: 'var(--red)', 1: 'var(--red)', 2: 'var(--orange)',
                        3: 'var(--yellow)', 4: 'var(--green)', 5: 'var(--green)'}
            qc = q_colors.get(rv.get('quality', 0), 'var(--text2)')
            review_html += f"""<div class="review-entry">
              <div class="q">Q: {rv.get('question_asked', '—')}</div>
              <div>A: {rv.get('user_response', '—')}</div>
              <div class="meta">
                Quality: <span style="color:{qc};font-weight:600">{rv.get('quality', '?')}/5</span>
                &nbsp;|&nbsp; {rv.get('llm_assessment', '')}
                &nbsp;|&nbsp; {rv.get('reviewed_at', '')}
              </div>
            </div>"""
    else:
        review_html = '<p style="color:var(--text2);font-size:13px">No reviews yet.</p>'

    body = f"""
    <p><a href="/concepts">← Concepts</a></p>
    <h2 style="margin:12px 0 4px">{detail['title']}</h2>
    <p style="color:var(--text2);margin-bottom:16px">{detail.get('description') or ''}</p>
    {info_html}
    <div class="section">
      <h4>Remarks ({len(remarks)})</h4>
      {remark_html}
    </div>
    <div class="section">
      <h4>Recent Reviews ({len(reviews)})</h4>
      {review_html}
    </div>"""
    return layout(detail['title'], body, active="concepts")


def page_reviews() -> str:
    conn = db._conn()
    rows = conn.execute("""
        SELECT rl.*, c.title as concept_title
        FROM review_log rl
        JOIN concepts c ON rl.concept_id = c.id
        ORDER BY rl.reviewed_at DESC
        LIMIT 50
    """).fetchall()
    conn.close()

    if not rows:
        body = '<div class="empty">No reviews yet. Start learning and get quizzed!</div>'
        return layout("Reviews", body, active="reviews")

    table_rows = ""
    for r in rows:
        rv = dict(r)
        q_colors = {0: 'var(--red)', 1: 'var(--red)', 2: 'var(--orange)',
                    3: 'var(--yellow)', 4: 'var(--green)', 5: 'var(--green)'}
        qc = q_colors.get(rv.get('quality', 0), 'var(--text2)')
        table_rows += f"""<tr>
          <td>{rv.get('reviewed_at', '—')}</td>
          <td><a href="/concept/{rv['concept_id']}">{rv['concept_title']}</a></td>
          <td style="max-width:200px">{rv.get('question_asked', '—')}</td>
          <td style="max-width:200px">{rv.get('user_response', '—')}</td>
          <td style="color:{qc};font-weight:600;text-align:center">{rv.get('quality', '?')}/5</td>
          <td style="font-size:12px;color:var(--text2)">{rv.get('llm_assessment', '')[:80]}</td>
        </tr>"""

    body = f"""
    <h2 style="margin-bottom:16px">Review Log (last 50)</h2>
    <table>
      <thead><tr><th>Date</th><th>Concept</th><th>Question</th><th>Answer</th><th>Quality</th><th>Assessment</th></tr></thead>
      <tbody>{table_rows}</tbody>
    </table>"""
    return layout("Reviews", body, active="reviews")


def page_404() -> str:
    return layout("404", '<div class="empty"><h2>404 — Page not found</h2><p><a href="/">Go home</a></p></div>')

# ============================================================================
# Activity (Action Log) page
# ============================================================================

# Humanized action labels for the Activity page
_ACTION_LABELS = {
    'add_concept': 'Added Concept',
    'add_topic': 'Added Topic',
    'update_concept': 'Updated Concept',
    'update_topic': 'Updated Topic',
    'delete_concept': 'Deleted Concept',
    'delete_topic': 'Deleted Topic',
    'link_concept': 'Linked Concept',
    'unlink_concept': 'Unlinked Concept',
    'link_topics': 'Linked Topics',
    'assess': 'Assessment',
    'quiz': 'Quiz Question',
    'remark': 'Added Remark',
    'suggest_topic': 'Suggested Topic',
    'fetch': 'Data Fetch',
    'list_topics': 'Listed Topics',
}

_SOURCE_CLASSES = {
    'discord': 'source-discord',
    'maintenance': 'source-maintenance',
    'scheduler': 'source-scheduler',
    'api': 'source-api',
    'cli': 'source-cli',
}


def _relative_time(dt_str: str) -> str:
    """Convert a datetime string to a human-friendly relative time."""
    try:
        dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return dt_str or '—'
    diff = datetime.now() - dt
    secs = int(diff.total_seconds())
    if secs < 60:
        return 'just now'
    if secs < 3600:
        m = secs // 60
        return f'{m} min ago'
    if secs < 86400:
        h = secs // 3600
        return f'{h} hr{"s" if h > 1 else ""} ago'
    days = secs // 86400
    if days == 1:
        return 'yesterday'
    if days < 30:
        return f'{days} days ago'
    return dt.strftime('%Y-%m-%d')


def _parse_action_summary(action: str, params_str: str) -> str:
    """Parse action params JSON into a human-readable summary with deep links."""
    try:
        params = json.loads(params_str) if params_str else {}
    except (json.JSONDecodeError, TypeError):
        return ''

    if action in ('add_concept', 'update_concept', 'delete_concept'):
        title = params.get('title') or params.get('new_title') or ''
        cid = params.get('concept_id', '')
        if title and cid:
            return f'<a href="/concept/{cid}">{_esc(title)}</a>'
        if title:
            return _esc(title)
        if cid:
            return f'<a href="/concept/{cid}">Concept #{cid}</a>'
        return ''

    if action in ('add_topic', 'update_topic', 'delete_topic'):
        title = params.get('title', '')
        tid = params.get('topic_id', '')
        if title and tid:
            return f'<a href="/topic/{tid}">{_esc(title)}</a>'
        if title:
            return _esc(title)
        if tid:
            return f'<a href="/topic/{tid}">Topic #{tid}</a>'
        return ''

    if action == 'assess':
        cid = params.get('concept_id', '')
        q = params.get('quality', '?')
        summary = f'Quality {q}/5'
        if cid:
            summary = f'<a href="/concept/{cid}">Concept #{cid}</a> — {summary}'
        return summary

    if action == 'quiz':
        cid = params.get('concept_id', '')
        if cid:
            return f'<a href="/concept/{cid}">Concept #{cid}</a>'
        return ''

    if action in ('link_concept', 'unlink_concept'):
        cid = params.get('concept_id', '')
        tids = params.get('topic_ids') or [params.get('topic_id', '')]
        parts = []
        if cid:
            parts.append(f'<a href="/concept/{cid}">#{cid}</a>')
        for tid in tids:
            if tid:
                parts.append(f'<a href="/topic/{tid}">Topic #{tid}</a>')
        return ' → '.join(parts)

    if action == 'remark':
        cid = params.get('concept_id', '')
        content = (params.get('content') or '')[:60]
        if cid:
            return f'<a href="/concept/{cid}">#{cid}</a> — {_esc(content)}'
        return _esc(content)

    if action == 'suggest_topic':
        return _esc(params.get('title', ''))

    if action == 'link_topics':
        pid = params.get('parent_id', '')
        cid_child = params.get('child_id', '')
        return f'<a href="/topic/{pid}">#{pid}</a> → <a href="/topic/{cid_child}">#{cid_child}</a>'

    return ''


def _esc(s: str) -> str:
    """HTML-escape a string."""
    return (s.replace('&', '&amp;').replace('<', '&lt;')
             .replace('>', '&gt;').replace('"', '&quot;'))


def page_actions(query_string: str = "") -> str:
    """Activity log page with server-side filtering and pagination."""
    qs = urllib.parse.parse_qs(query_string)
    action_filter = qs.get('action', [None])[0]
    source_filter = qs.get('source', [None])[0]
    search = qs.get('q', [None])[0]
    time_filter = qs.get('time', ['all'])[0]
    page = max(1, int(qs.get('page', [1])[0]))
    per_page = 50

    # Time filter
    since = None
    if time_filter == 'today':
        since = datetime.now().replace(hour=0, minute=0, second=0)
    elif time_filter == '7d':
        since = datetime.now() - timedelta(days=7)
    elif time_filter == '30d':
        since = datetime.now() - timedelta(days=30)

    # Filter params that are empty strings should be None
    if action_filter == '':
        action_filter = None
    if source_filter == '':
        source_filter = None
    if search == '':
        search = None

    total = db.get_action_log_count(
        action_filter=action_filter, source_filter=source_filter,
        since=since, search=search,
    )
    entries = db.get_action_log(
        limit=per_page, offset=(page - 1) * per_page,
        action_filter=action_filter, source_filter=source_filter,
        since=since, search=search,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)

    # Get distinct values for filter dropdowns
    distinct_actions = db.get_distinct_actions()
    distinct_sources = db.get_distinct_sources()

    # Build filter toolbar
    action_options = '<option value="">All Actions</option>'
    for a in distinct_actions:
        sel = ' selected' if a == action_filter else ''
        label = _ACTION_LABELS.get(a, a)
        action_options += f'<option value="{a}"{sel}>{label}</option>'

    source_options = '<option value="">All Sources</option>'
    for s in distinct_sources:
        sel = ' selected' if s == source_filter else ''
        source_options += f'<option value="{s}"{sel}>{s.title()}</option>'

    def _time_btn(val, label):
        active = ' active' if time_filter == val else ''
        return f'<a href="?{_build_qs(time=val)}" class="filter-btn{active}">{label}</a>'

    def _build_qs(**overrides):
        p = {}
        if action_filter:
            p['action'] = action_filter
        if source_filter:
            p['source'] = source_filter
        if search:
            p['q'] = search
        p['time'] = time_filter
        p['page'] = '1'
        p.update({k: v for k, v in overrides.items() if v})
        return urllib.parse.urlencode(p)

    search_val = _esc(search) if search else ''

    toolbar = f'''<div class="concepts-toolbar">
      <div class="toolbar-search">
        <form method="get" action="/actions" style="display:contents">
          <input type="hidden" name="action" value="{action_filter or ''}">
          <input type="hidden" name="source" value="{source_filter or ''}">
          <input type="hidden" name="time" value="{time_filter}">
          <input type="text" name="q" value="{search_val}" placeholder="Search actions\u2026" autocomplete="off">
        </form>
      </div>
      <select onchange="location.href='/actions?'+new URLSearchParams({{action:this.value,source:'{source_filter or ''}',time:'{time_filter}',q:'{search_val}'}})">
        {action_options}
      </select>
      <select onchange="location.href='/actions?'+new URLSearchParams({{source:this.value,action:'{action_filter or ''}',time:'{time_filter}',q:'{search_val}'}})">
        {source_options}
      </select>
      <div class="filter-btn-group">
        {_time_btn('today', 'Today')}
        {_time_btn('7d', '7 days')}
        {_time_btn('30d', '30 days')}
        {_time_btn('all', 'All')}
      </div>
    </div>'''

    # Table rows
    if not entries:
        table_html = '<div class="empty">No actions logged yet. Start learning via the Discord bot!</div>'
    else:
        rows_html = ''
        for e in entries:
            action = e.get('action', '')
            source = e.get('source', 'discord')
            result_type = e.get('result_type', '')
            created = e.get('created_at', '')

            # Humanized label
            label = _ACTION_LABELS.get(action, action)

            # Source pill
            source_cls = _SOURCE_CLASSES.get(source, 'source-cli')
            source_pill = f'<span class="tag {source_cls}">{source.title()}</span>'

            # Status badge
            if result_type == 'error':
                status = '<span class="badge due">Error</span>'
            else:
                status = '<span class="badge ok">\u2713</span>'

            # Summary
            summary = _parse_action_summary(action, e.get('params', ''))

            # Relative time
            rel_time = _relative_time(created)

            # Detail row content (for expand/collapse)
            params_display = ''
            try:
                params_obj = json.loads(e.get('params', '{}') or '{}')
                params_display = '\n'.join(
                    f'<tr><td style="color:var(--text2);padding:3px 12px 3px 0;font-size:12px">{_esc(str(k))}</td>'
                    f'<td style="font-size:12px;padding:3px 0">{_esc(str(v)[:200])}</td></tr>'
                    for k, v in params_obj.items()
                )
            except (json.JSONDecodeError, TypeError):
                params_display = f'<tr><td colspan="2" style="font-size:12px">{_esc(str(e.get("params", "")))[:200]}</td></tr>'

            result_text = _esc(str(e.get('result', ''))[:300])

            rows_html += f'''<tr class="action-row" onclick="this.classList.toggle('expanded');this.nextElementSibling.style.display=this.classList.contains('expanded')?'table-row':'none'">
              <td title="{_esc(created)}"><span class="action-chevron">\u25b8</span> {rel_time}</td>
              <td>{source_pill}</td>
              <td>{label}</td>
              <td>{summary}</td>
              <td>{status}</td>
            </tr>
            <tr class="detail-row" style="display:none">
              <td colspan="5">
                <div class="action-detail">
                  <table style="margin:0">{params_display}</table>
                  {f'<div style="margin-top:8px;font-size:12px;color:var(--text2)">Result: {result_text}</div>' if result_text else ''}
                  <div style="margin-top:4px;font-size:11px;color:var(--text2)">Raw action: {_esc(action)} | {_esc(created)}</div>
                </div>
              </td>
            </tr>'''

        table_html = f'''<table class="activity-table">
          <thead><tr>
            <th style="width:120px">Time</th>
            <th style="width:100px">Source</th>
            <th style="width:140px">Action</th>
            <th>Summary</th>
            <th style="width:60px">Status</th>
          </tr></thead>
          <tbody>{rows_html}</tbody>
        </table>'''

    # Pagination
    pagination = ''
    if total_pages > 1:
        prev_link = ''
        next_link = ''
        if page > 1:
            prev_link = f'<a href="/actions?{_build_qs(page=str(page-1))}" class="btn btn-sm" style="background:var(--surface);color:var(--text);border:1px solid var(--border)">← Prev</a>'
        if page < total_pages:
            next_link = f'<a href="/actions?{_build_qs(page=str(page+1))}" class="btn btn-sm" style="background:var(--surface);color:var(--text);border:1px solid var(--border)">Next →</a>'
        pagination = f'''<div style="display:flex;justify-content:space-between;align-items:center;margin-top:16px;font-size:13px">
          {prev_link}
          <span style="color:var(--text2)">Page {page} of {total_pages} ({total} entries)</span>
          {next_link}
        </div>'''

    body = f'''
    <h2 style="margin-bottom:4px">Activity Log</h2>
    <p style="color:var(--text2);font-size:13px;margin-bottom:16px">{total} action{"s" if total != 1 else ""} recorded</p>
    {toolbar}
    {table_html}
    {pagination}'''

    return layout("Activity", body, active="actions")


# ============================================================================
# Graph page
# ============================================================================

def page_graph() -> str:
    """Knowledge graph visualization page. Full-bleed layout."""
    import config

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

# ============================================================================
# HTTP Handler
# ============================================================================

MIME_TYPES = {
    '.css': 'text/css',
    '.js': 'application/javascript',
    '.json': 'application/json',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # Static file serving
        if path.startswith("/static/"):
            self._serve_static(path[8:])  # strip /static/
            return

        try:
            if path == "/":
                html = page_dashboard()
            elif path == "/topics":
                html = page_topics()
            elif path.startswith("/topic/"):
                tid = int(path.split("/")[2])
                html = page_topic_detail(tid)
            elif path == "/concepts":
                html = page_concepts()
            elif path == "/graph":
                html = page_graph()
            elif path.startswith("/concept/"):
                cid = int(path.split("/")[2])
                html = page_concept_detail(cid)
            elif path == "/reviews":
                html = page_reviews()
            elif path == "/actions":
                html = page_actions(parsed.query or "")
            elif path == "/api/stats":
                self._json_response(db.get_review_stats())
                return
            elif path == "/api/topics":
                self._json_response(db.get_topic_map())
                return
            elif path == "/api/due":
                self._json_response(db.get_due_concepts())
                return
            elif path == "/api/actions":
                # Parse query params for filtering
                qs = urllib.parse.parse_qs(parsed.query or "")
                limit = min(200, int(qs.get('limit', [50])[0]))
                offset = int(qs.get('offset', [0])[0])
                action_f = qs.get('action', [None])[0] or None
                source_f = qs.get('source', [None])[0] or None
                entries = db.get_action_log(
                    limit=limit, offset=offset,
                    action_filter=action_f, source_filter=source_f,
                )
                self._json_response({"entries": entries, "total": db.get_action_log_count(
                    action_filter=action_f, source_filter=source_f)})
                return
            else:
                html = page_404()

            self._html_response(html)

        except Exception as e:
            self._html_response(
                layout("Error", f'<div class="flash error">Error: {e}</div><p><a href="/">Go home</a></p>'),
                status=500
            )

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # CSRF: require custom header (browsers won't send cross-origin without CORS preflight)
        if self.headers.get("X-Requested-With") != "fetch":
            self._json_response({"ok": False, "error": "Forbidden"}, status=403)
            return

        # Read body (for future extensibility)
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            length = 0
        if length > 0:
            self.rfile.read(length)  # consume body

        try:
            # DELETE concept: POST /api/concept/<id>/delete
            parts = path.split("/")
            if (len(parts) == 5 and parts[1] == "api"
                    and parts[2] == "concept" and parts[4] == "delete"):
                try:
                    cid = int(parts[3])
                except ValueError:
                    self._json_response({"ok": False, "error": "Invalid concept ID"}, status=400)
                    return
                deleted = db.delete_concept(cid)
                if deleted:
                    self._json_response({"ok": True})
                else:
                    self._json_response({"ok": False, "error": "Concept not found"}, status=404)
                return

            self._json_response({"ok": False, "error": "Not found"}, status=404)

        except Exception as e:
            self._json_response({"ok": False, "error": str(e)}, status=500)

    def _serve_static(self, rel_path: str):
        """Serve a file from the static/ directory."""
        # Prevent path traversal
        safe_path = Path(rel_path).name  # only the filename, no subdirs
        file_path = STATIC_DIR / safe_path
        if not file_path.is_file():
            self.send_error(404, "Static file not found")
            return

        ext = file_path.suffix.lower()
        content_type = MIME_TYPES.get(ext, mimetypes.guess_type(str(file_path))[0] or 'application/octet-stream')

        try:
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8" if ext in ('.css', '.js', '.json') else content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            self.send_error(500, "Error reading static file")

    def _html_response(self, html: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _json_response(self, data, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode("utf-8"))

    def log_message(self, format, *args):
        # Quieter logging
        pass


# ============================================================================
# Main
# ============================================================================

def main(skip_init: bool = False):
    if not skip_init:
        db.init_databases()
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Learning Agent DB UI running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop.")

    # Fast shutdown on Windows: signal handler calls shutdown() from a thread
    # Only works when running in the main thread (not when bot spawns webui in a thread)
    if threading.current_thread() is threading.main_thread():
        def _signal_shutdown(sig, frame):
            print("\nShutting down...")
            threading.Thread(target=server.shutdown, daemon=True).start()

        signal.signal(signal.SIGINT, _signal_shutdown)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, _signal_shutdown)

    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("Server stopped.")


if __name__ == "__main__":
    main()
