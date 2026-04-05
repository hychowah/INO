"""Topics list, topic detail, and breadcrumb pages."""

import db
from webui.helpers import layout, mastery_progress_bar, score_bar
from webui.pages.dashboard import compute_subtree_stats, render_tree_node


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
        parents = t.get("parent_ids", [])
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


def page_topics() -> str:
    topics = db.get_all_topics()
    if not topics:
        body = '<div class="empty">No topics yet.</div>'
        return layout("Topics", body, active="topics")

    topic_map = db.get_topic_map()
    by_id = {t["id"]: t for t in topic_map}
    subtree_stats = compute_subtree_stats(topic_map)

    roots = [t for t in topic_map if not t["parent_ids"]]

    # Toolbar
    toolbar = """
    <div class="tree-toolbar">
      <input type="text" id="tree-search" placeholder="Search topics..." autocomplete="off">
      <span id="tree-match-count" class="match-count"></span>
      <button class="btn btn-sm btn-primary" id="tree-expand-all">Expand All</button>
      <button class="btn btn-sm" id="tree-collapse-all" style="background:var(--surface);color:var(--text);border:1px solid var(--border)">Collapse All</button>
    </div>"""

    # Build tree
    tree_html = '<div class="topic-tree">'
    for r in sorted(roots, key=lambda x: x["title"]):
        tree_html += render_tree_node(r, by_id, subtree_stats, expanded_default=True)

    # Orphans
    shown_ids = set()

    def collect_ids(t):
        shown_ids.add(t["id"])
        for cid in t.get("child_ids", []):
            c = by_id.get(cid)
            if c:
                collect_ids(c)

    for r in roots:
        collect_ids(r)
    orphans = [t for t in topic_map if t["id"] not in shown_ids]
    if orphans:
        tree_html += '<div class="orphan-section"><h4>⚠ Uncategorized (no parent)</h4>'
        for o in sorted(orphans, key=lambda x: x["title"]):
            tree_html += render_tree_node(o, by_id, subtree_stats, expanded_default=False)
        tree_html += "</div>"

    tree_html += "</div>"

    # Summary stats
    total_topics = len(topic_map)
    root_count = len(roots)
    orphan_count = len(orphans)
    summary = f"{total_topics} topics ({root_count} root"
    if orphan_count:
        summary += f", {orphan_count} uncategorized"
    summary += ")"

    body = f"""
    <h2 style="margin-bottom:4px">Topics</h2>
    <p style="color:var(--text2);font-size:13px;margin-bottom:16px">{summary}</p>
    {toolbar}
    {tree_html}"""

    return layout(
        "Topics", body, active="topics", extra_scripts='<script src="/static/tree.js"></script>'
    )


def page_topic_detail(topic_id: int) -> str:
    topic = db.get_topic(topic_id)
    if not topic:
        return layout("Not Found", '<div class="empty">Topic not found.</div>')

    concepts = db.get_concepts_for_topic(topic_id)
    parents = db.get_topic_parents(topic_id)
    children = db.get_topic_children(topic_id)

    # Build breadcrumb using the full topic map
    topic_map = db.get_topic_map()
    by_id_full = {t["id"]: t for t in topic_map}
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
            ss = subtree_stats.get(c["id"], {})
            child_tm = by_id_full.get(c["id"], {})
            own_count = child_tm.get("concept_count", 0)
            total = ss.get("total_concepts", own_count)
            avg_m = ss.get("subtree_avg_mastery", 0)
            count_str = (
                f"{own_count} / {total} concepts" if total != own_count else f"{own_count} concepts"
            )
            child_cards += f"""<a href="/topic/{c["id"]}" class="child-topic-card">
              <div class="card-title">{c["title"]}</div>
              <td>{mastery_progress_bar(avg_m)} <span style="font-size:12px;color:var(--text2)">{count_str} · score {avg_m}/100</span></td>
            </a>"""
        child_cards += "</div>"
        rel_html += f'<div class="section"><h4>Subtopics ({len(children)})</h4>{child_cards}</div>'

    # Concepts table
    if concepts:
        rows = ""
        for c in concepts:
            due = ""
            if c["next_review_at"]:
                from datetime import datetime as dt

                try:
                    nr = dt.strptime(c["next_review_at"], "%Y-%m-%d %H:%M:%S")
                    if nr <= dt.now():
                        due = '<span class="badge due">DUE</span>'
                except Exception:
                    pass
            remark = (c.get("latest_remark") or "")[:60]
            rows += f"""<tr>
              <td><a href="/concept/{c["id"]}">#{c["id"]}</a></td>
              <td><a href="/concept/{c["id"]}">{c["title"]}</a></td>
              <td>{score_bar(c["mastery_level"])}</td>
              <td>{c.get("interval_days", 1)}d</td>
              <td>{c["next_review_at"] or "—"} {due}</td>
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
    <h2 style="margin:12px 0 4px">{topic["title"]}</h2>
    <p style="color:var(--text2)">{topic.get("description") or ""}</p>
    {rel_html}
    <div class="section">
      <h4>Concepts ({len(concepts)})</h4>
      {concept_html}
    </div>"""
    return layout(topic["title"], body, active="topics")
