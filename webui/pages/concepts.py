"""Concepts list and concept detail pages."""

import json

import db
from webui.helpers import score_bar, _esc, layout


def page_concepts() -> str:
    # Get all concepts with structured topic data
    concepts = db.get_all_concepts_with_topics()
    # Get flat topic list for the filter dropdown
    all_topics = db.get_all_topics()
    topic_list = [{'id': t['id'], 'title': t['title']} for t in all_topics]

    # Serialize for client-side JS
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
        <input type="text" id="concept-search" placeholder="Search concepts\u2026" autocomplete="off">
        <button class="search-clear" id="search-clear" title="Clear search">\u2715</button>
      </div>
      <select id="concept-topic-filter">
        <option value="">All Topics</option>
      </select>
      <div class="filter-btn-group" id="status-filter">
        <button class="filter-btn active" data-status="all">All</button>
        <button class="filter-btn" data-status="due">\U0001f534 Due</button>
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
        <h3>\u26a0\ufe0f Delete Concept</h3>
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
        except Exception:
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

    # Relations
    relations = db.get_relations(concept_id)
    RELATION_COLORS = {
        'builds_on': '#4CAF50', 'contrasts_with': '#FF9800',
        'commonly_confused': '#F44336', 'applied_together': '#2196F3',
        'same_phenomenon': '#9C27B0',
    }
    if relations:
        rel_rows = ""
        for rel in relations:
            rtype = rel['relation_type']
            color = RELATION_COLORS.get(rtype, 'var(--text2)')
            label = rtype.replace('_', ' ')
            note_html = f'<div style="font-size:12px;color:var(--text2);margin-top:2px">{rel["note"]}</div>' if rel.get('note') else ''
            rel_rows += f"""<div class="relation-row">
              <a href="/concept/{rel['other_concept_id']}">{rel['other_title']}</a>
              <span class="relation-badge" style="background-color:{color}">{label}</span>
              {score_bar(rel['other_mastery'])}
              {note_html}
            </div>"""
        relations_html = f"""<div class="section">
      <h4>Relations ({len(relations)})</h4>
      {rel_rows}
    </div>"""
    else:
        relations_html = """<div class="section">
      <h4>Relations (0)</h4>
      <p style="color:var(--text2);font-size:13px">No related concepts yet.</p>
    </div>"""

    # Remark summary (cached)
    remark_summary = detail.get('remark_summary', '')
    remark_updated = detail.get('remark_updated_at', '')
    if remark_summary:
        summary_html = f"""<div class="remark" style="border-left:3px solid var(--accent);padding-left:12px;margin-bottom:12px">
              <div style="font-size:11px;color:var(--text2);margin-bottom:4px">Current summary (updated {remark_updated or 'N/A'})</div>
              {remark_summary}
            </div>"""
    else:
        summary_html = ''

    # Remarks (full history)
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

    # Last quiz generator (P1) output
    p1_raw = detail.get('last_quiz_generator_output', '')
    if p1_raw:
        try:
            p1_data = json.loads(p1_raw)
            p1_question = _esc(p1_data.get('question', ''))
            p1_type = _esc(p1_data.get('question_type', ''))
            p1_diff = _esc(str(p1_data.get('difficulty', '')))
            p1_facet = _esc(p1_data.get('target_facet', ''))
            p1_reasoning = _esc(p1_data.get('reasoning', ''))
            p1_cids = p1_data.get('concept_ids', [])

            p1_fields = f'<div class="p1-question">{p1_question}</div>'
            p1_meta_parts = []
            if p1_type:
                p1_meta_parts.append(f'<span class="p1-tag">Type: {p1_type}</span>')
            if p1_diff:
                p1_meta_parts.append(f'<span class="p1-tag">Difficulty: {p1_diff}</span>')
            if p1_facet:
                p1_meta_parts.append(f'<span class="p1-tag">Facet: {p1_facet}</span>')
            if p1_cids:
                cid_links = ', '.join(f'<a href="/concept/{_esc(str(cid))}">#{_esc(str(cid))}</a>' for cid in p1_cids)
                p1_meta_parts.append(f'<span class="p1-tag">Concepts: {cid_links}</span>')
            p1_meta = f'<div class="p1-meta">{" ".join(p1_meta_parts)}</div>' if p1_meta_parts else ''
            p1_reasoning_html = f'<div class="p1-reasoning">{p1_reasoning}</div>' if p1_reasoning else ''
            p1_html = f'{p1_fields}{p1_meta}{p1_reasoning_html}'
        except (json.JSONDecodeError, TypeError):
            p1_html = f'<pre style="font-size:12px;color:var(--text2);white-space:pre-wrap">{_esc(p1_raw[:2000])}</pre>'
    else:
        p1_html = '<p style="color:var(--text2);font-size:13px">No quiz generated yet.</p>'

    body = f"""
    <p><a href="/concepts">\u2190 Concepts</a></p>
    <h2 style="margin:12px 0 4px">{detail['title']}</h2>
    <p style="color:var(--text2);margin-bottom:16px">{detail.get('description') or ''}</p>
    {info_html}
    {relations_html}
    <div class="section">
      <h4>Remarks ({len(remarks)})</h4>
      {summary_html}
      {remark_html}
    </div>
    <div class="section">
      <h4>Recent Reviews ({len(reviews)})</h4>
      {review_html}
    </div>
    <div class="section">
      <h4>\U0001f916 Last Quiz Generator Output (P1)</h4>
      {p1_html}
    </div>"""
    return layout(detail['title'], body, active="concepts")
