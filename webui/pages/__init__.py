"""
WebUI pages package.
Re-exports all page renderer functions for backward compatibility.
Importing as `from webui.pages import page_dashboard` continues to work
after the split from the monolithic pages.py.
"""

from webui.pages.activity import page_actions
from webui.pages.chat import page_chat
from webui.pages.concepts import page_concept_detail, page_concepts
from webui.pages.dashboard import page_dashboard
from webui.pages.graph import page_graph
from webui.pages.reviews import page_404, page_forecast, page_reviews
from webui.pages.topics import page_topic_detail, page_topics

__all__ = [
    "page_dashboard",
    "page_chat",
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
