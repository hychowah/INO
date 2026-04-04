"""
WebUI pages package.
Re-exports all page renderer functions for backward compatibility.
Importing as `from webui.pages import page_dashboard` continues to work
after the split from the monolithic pages.py.
"""
from webui.pages.dashboard import page_dashboard
from webui.pages.topics import page_topics, page_topic_detail
from webui.pages.concepts import page_concepts, page_concept_detail
from webui.pages.reviews import page_reviews, page_404, page_forecast
from webui.pages.activity import page_actions
from webui.pages.graph import page_graph

__all__ = [
    "page_dashboard",
    "page_topics",
    "page_topic_detail",
    "page_concepts",
    "page_concept_detail",
    "page_reviews",
    "page_404",
    "page_forecast",
    "page_actions",
    "page_graph",
]
