"""Activity (action log) page."""

import json
import urllib.parse
from datetime import datetime, timedelta

import db
from webui.helpers import layout, _esc, _parse_action_summary, _relative_time


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
