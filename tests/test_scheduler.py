import json
from unittest.mock import AsyncMock, patch

import pytest

import db
from services import scheduler
from bot.messages import send_review_question
from services.views import QuizQuestionView


class _MockUser:
    async def send(self, content, view=None):
        return type('Message', (), {'id': 1})()


class _MockBot:
    def __init__(self, user):
        self._user = user

    async def fetch_user(self, _user_id):
        return self._user


@pytest.mark.anyio
async def test_send_review_quiz_attaches_skip_button_for_eligible_concept(test_db):
    cid = db.add_concept("Eligible Review", "Desc")
    db.update_concept(cid, review_count=3)
    user = _MockUser()
    mock_send_long_with_view = AsyncMock(return_value=type('Message', (), {'id': 1})())

    with patch.object(scheduler, '_bot', _MockBot(user)), \
         patch.object(scheduler, '_authorized_user_id', 123), \
         patch('services.tools.set_action_source'), \
         patch('services.pipeline.generate_quiz_question', new=AsyncMock(return_value={'question': 'Q'})), \
         patch('services.pipeline.package_quiz_for_discord', new=AsyncMock(return_value='QUIZ')), \
         patch('services.pipeline.execute_llm_response', new=AsyncMock(return_value='REPLY: What is eligible?')), \
         patch('services.pipeline.process_output', return_value=('reply', 'What is eligible?')), \
         patch('bot.messages.send_long_with_view', new=mock_send_long_with_view):
        await scheduler._send_review_quiz(f'{cid}|context')

    mock_send_long_with_view.assert_awaited_once()
    call = mock_send_long_with_view.await_args
    assert call.args[0] == user.send
    assert call.args[1] == '📚 **Learning Review**\nWhat is eligible?\n\n📖 **Eligible Review** · Score: 0/100 · Review #4'
    assert isinstance(call.kwargs['view'], QuizQuestionView)
    assert call.kwargs['view'].concept_id == cid
    assert db.get_session('last_quiz_question') == 'What is eligible?'

    pending = json.loads(db.get_session('pending_review'))
    assert pending['concept_id'] == cid
    assert pending['concept_title'] == 'Eligible Review'


@pytest.mark.anyio
async def test_send_review_quiz_omits_skip_button_for_ineligible_concept(test_db):
    cid = db.add_concept("New Review", "Desc")
    db.update_concept(cid, review_count=1)
    user = _MockUser()
    mock_send_long_with_view = AsyncMock(return_value=type('Message', (), {'id': 1})())

    with patch.object(scheduler, '_bot', _MockBot(user)), \
         patch.object(scheduler, '_authorized_user_id', 123), \
         patch('services.tools.set_action_source'), \
         patch('services.pipeline.generate_quiz_question', new=AsyncMock(return_value={'question': 'Q'})), \
         patch('services.pipeline.package_quiz_for_discord', new=AsyncMock(return_value='QUIZ')), \
         patch('services.pipeline.execute_llm_response', new=AsyncMock(return_value='REPLY: What is new?')), \
         patch('services.pipeline.process_output', return_value=('reply', 'What is new?')), \
         patch('bot.messages.send_long_with_view', new=mock_send_long_with_view):
        await scheduler._send_review_quiz(f'{cid}|context')

    mock_send_long_with_view.assert_awaited_once()
    call = mock_send_long_with_view.await_args
    assert call.args[0] == user.send
    assert call.args[1] == '📚 **Learning Review**\nWhat is new?\n\n📖 **New Review** · Score: 0/100 · Review #2\n_(skip unlocks after 1 more review(s))_'
    assert call.kwargs['view'] is None


@pytest.mark.anyio
async def test_send_review_question_attaches_skip_button_at_boundary(test_db):
    cid = db.add_concept("Boundary Review", "Desc")
    db.update_concept(cid, review_count=2)
    user = _MockUser()
    mock_send_long_with_view = AsyncMock(return_value=type('Message', (), {'id': 1})())

    async def fake_handler(_text, _author):
        return "ignored", None, None, None

    with patch('bot.messages.send_long_with_view', new=mock_send_long_with_view):
        await send_review_question(user.send, 'What is the boundary?', cid, fake_handler)

    mock_send_long_with_view.assert_awaited_once()
    call = mock_send_long_with_view.await_args
    assert call.args[1] == '📚 **Learning Review**\nWhat is the boundary?\n\n📖 **Boundary Review** · Score: 0/100 · Review #3'
    assert isinstance(call.kwargs['view'], QuizQuestionView)
    assert call.kwargs['view'].concept_id == cid
