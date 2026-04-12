"""Compatibility alias for the shared chat session controller."""

import sys

from services import chat_session as _chat_session

sys.modules[__name__] = _chat_session