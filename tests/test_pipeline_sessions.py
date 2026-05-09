from unittest.mock import Mock, patch

from services import llm_runtime, state


def test_get_conv_session_isolated_per_current_user():
    previous_sessions = dict(llm_runtime._conv_sessions)
    llm_runtime._conv_sessions.clear()

    try:
        with state.current_user_scope("user-a"):
            session_a, is_new_a = llm_runtime._get_conv_session()
            session_a_repeat, is_new_a_repeat = llm_runtime._get_conv_session()

        with state.current_user_scope("user-b"):
            session_b, is_new_b = llm_runtime._get_conv_session()

        assert is_new_a is True
        assert is_new_a_repeat is False
        assert is_new_b is True
        assert session_a == session_a_repeat
        assert session_a != session_b
    finally:
        llm_runtime._conv_sessions.clear()
        llm_runtime._conv_sessions.update(previous_sessions)


def test_reset_conversation_session_clears_only_current_user_session():
    previous_sessions = dict(llm_runtime._conv_sessions)
    llm_runtime._conv_sessions.clear()

    try:
        with state.current_user_scope("user-a"):
            session_a, _ = llm_runtime._get_conv_session()
        with state.current_user_scope("user-b"):
            session_b, _ = llm_runtime._get_conv_session()

        provider = Mock()
        with patch("services.llm_runtime.get_provider", return_value=provider):
            with state.current_user_scope("user-a"):
                llm_runtime.reset_conversation_session()

        provider.clear_session.assert_called_once_with(session_a)
        assert "user-a" not in llm_runtime._conv_sessions
        assert llm_runtime._conv_sessions["user-b"][0] == session_b
    finally:
        llm_runtime._conv_sessions.clear()
        llm_runtime._conv_sessions.update(previous_sessions)