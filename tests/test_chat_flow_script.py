from argparse import Namespace

import pytest

from scripts import test_chat_flow


def test_expand_turns_builds_review_scenario_then_manual_turns():
    args = Namespace(
        scenario="review",
        answer=["first answer", "second answer"],
        turn=["follow-up turn"],
    )

    assert test_chat_flow.expand_turns(args) == [
        "/review",
        "first answer",
        "second answer",
        "follow-up turn",
    ]


def test_expand_turns_rejects_answers_without_review_scenario():
    args = Namespace(
        scenario=None,
        answer=["orphan answer"],
        turn=[],
    )

    with pytest.raises(ValueError, match="--answer requires --scenario review"):
        test_chat_flow.expand_turns(args)


def test_summarize_actions_compacts_known_ui_blocks():
    actions = [
        {
            "type": "multiple_choice",
            "title": "Choose an answer",
            "choices": [{"label": "A"}, {"label": "B"}],
        },
        {
            "type": "button_group",
            "title": "Quiz follow-up",
            "buttons": [{"label": "Next due"}, {"label": "Quiz again"}],
        },
    ]

    assert test_chat_flow.summarize_actions(actions) == [
        {
            "type": "multiple_choice",
            "title": "Choose an answer",
            "choices": ["A", "B"],
        },
        {
            "type": "button_group",
            "title": "Quiz follow-up",
            "buttons": ["Next due", "Quiz again"],
        },
    ]