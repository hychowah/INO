"""
WebUI helpers — shared rendering utilities used by pages and server.
"""

import json
from datetime import datetime


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
        ("forecast", "Forecast"),
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


def _esc(s: str) -> str:
    """HTML-escape a string."""
    return (s.replace('&', '&amp;').replace('<', '&lt;')
             .replace('>', '&gt;').replace('"', '&quot;'))


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
