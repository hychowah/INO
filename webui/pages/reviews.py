"""Reviews log page, 404 page, and review forecast page."""

import db
from webui.helpers import layout


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
        q_colors = {
            0: "var(--red)",
            1: "var(--red)",
            2: "var(--orange)",
            3: "var(--yellow)",
            4: "var(--green)",
            5: "var(--green)",
        }
        qc = q_colors.get(rv.get("quality", 0), "var(--text2)")
        table_rows += f"""<tr>
          <td>{rv.get("reviewed_at", "—")}</td>
          <td><a href="/concept/{rv["concept_id"]}">{rv["concept_title"]}</a></td>
          <td style="max-width:200px">{rv.get("question_asked", "—")}</td>
          <td style="max-width:200px">{rv.get("user_response", "—")}</td>
          <td style="color:{qc};font-weight:600;text-align:center">{rv.get("quality", "?")}/5</td>
          <td style="font-size:12px;color:var(--text2)">{rv.get("llm_assessment", "")[:80]}</td>
        </tr>"""

    body = f"""
    <h2 style="margin-bottom:16px">Review Log (last 50)</h2>
    <table>
      <thead><tr><th>Date</th><th>Concept</th><th>Question</th><th>Answer</th><th>Quality</th><th>Assessment</th></tr></thead>
      <tbody>{table_rows}</tbody>
    </table>"""
    return layout("Reviews", body, active="reviews")


def page_404() -> str:
    return layout(
        "404",
        '<div class="empty"><h2>404 — Page not found</h2><p><a href="/">Go home</a></p></div>',
    )


def page_forecast() -> str:
    """Review forecast page — D3 bar chart of concepts due in upcoming periods."""
    body = """
    <h2 style="margin-bottom:4px">Review Forecast</h2>
    <p style="color:var(--text2);font-size:13px;margin-bottom:16px">
      Concepts scheduled for review over the coming periods.
      Click a bar to see which concepts are due.
    </p>
    <div class="forecast-controls" style="margin-bottom:16px">
      <div class="filter-btn-group" id="forecast-range-toggle">
        <button class="filter-btn" data-range="days">7 Days</button>
        <button class="filter-btn active" data-range="weeks">7 Weeks</button>
        <button class="filter-btn" data-range="months">7 Months</button>
      </div>
    </div>
    <div class="card" id="forecast-chart-card">
      <div id="forecast-chart" style="min-height:260px"></div>
    </div>
    <div class="card" id="forecast-concepts-card" style="display:none;margin-top:16px">
      <div id="forecast-concepts-header" style="font-weight:600;margin-bottom:10px"></div>
      <div id="forecast-concepts"></div>
    </div>"""
    return layout(
        "Review Forecast",
        body,
        active="forecast",
        extra_scripts=(
            '<script src="https://d3js.org/d3.v7.min.js"></script>\n'
            '<script src="/static/forecast.js?v=1"></script>'
        ),
    )
