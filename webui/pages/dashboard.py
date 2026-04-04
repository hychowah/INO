"""Dashboard page and shared tree-rendering utilities."""

import db
from webui.helpers import layout, score_bar, mastery_progress_bar


# ============================================================================
# Tree rendering (shared — also imported by topics.py)
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


# ============================================================================
# Dashboard page
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
