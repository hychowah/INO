from unittest.mock import Mock, patch

from services import pipeline, state


def test_get_conv_session_isolated_per_current_user():
    previous_sessions = dict(pipeline._conv_sessions)
    pipeline._conv_sessions.clear()

    try:
        with state.current_user_scope("user-a"):
            session_a, is_new_a = pipeline._get_conv_session()
            session_a_repeat, is_new_a_repeat = pipeline._get_conv_session()

        with state.current_user_scope("user-b"):
            session_b, is_new_b = pipeline._get_conv_session()

        assert is_new_a is True
        assert is_new_a_repeat is False
        assert is_new_b is True
        assert session_a == session_a_repeat
        assert session_a != session_b
    finally:
        pipeline._conv_sessions.clear()
        pipeline._conv_sessions.update(previous_sessions)


def test_reset_conversation_session_clears_only_current_user_session():
    previous_sessions = dict(pipeline._conv_sessions)
    pipeline._conv_sessions.clear()

    try:
        with state.current_user_scope("user-a"):
            session_a, _ = pipeline._get_conv_session()
        with state.current_user_scope("user-b"):
            session_b, _ = pipeline._get_conv_session()

        provider = Mock()
        with patch("services.pipeline.get_provider", return_value=provider):
            with state.current_user_scope("user-a"):
                pipeline.reset_conversation_session()

        provider.clear_session.assert_called_once_with(session_a)
        assert "user-a" not in pipeline._conv_sessions
        assert pipeline._conv_sessions["user-b"][0] == session_b
    finally:
        pipeline._conv_sessions.clear()
        pipeline._conv_sessions.update(previous_sessions)