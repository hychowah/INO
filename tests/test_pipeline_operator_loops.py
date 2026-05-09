import asyncio

from services import pipeline


def test_call_maintenance_loop_forwards_contract(monkeypatch):
    captured = {}

    async def fake_call_action_loop(**kwargs):
        captured.update(kwargs)
        return "REPLY: ok", []

    monkeypatch.setattr(pipeline, "call_action_loop", fake_call_action_loop)

    report, proposed = asyncio.run(pipeline.call_maintenance_loop("diagnostic context"))

    assert report == "REPLY: ok"
    assert proposed == []
    assert captured["mode"] == "maintenance"
    assert captured["safe_actions"] == pipeline.SAFE_MAINTENANCE_ACTIONS
    assert captured["max_actions"] == pipeline.MAX_MAINTENANCE_ACTIONS
    assert captured["context"] == "diagnostic context"
    assert "Do NOT attempt to merge duplicate concepts" in captured["preamble"]
    assert "Do NOT use update_concept to change mastery_level" in captured["preamble"]