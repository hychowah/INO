"""Tests for parser.py JSON extraction and safety net fixes.

Covers:
- _extract_json_object: try-each-} with last-valid-parse (DEVNOTES §9.2)
- _extract_json_str: same approach, returns raw string
- extract_fetch_params: refactored to reuse _extract_json_object
- process_output: safety net for raw JSON
- parse_llm_response: end-to-end with code-in-strings
"""

import json
from services.parser import (
    _extract_json_object,
    _extract_json_str,
    extract_fetch_params,
    parse_llm_response,
    process_output,
)


# ============================================================================
# _extract_json_object — basic cases
# ============================================================================

class TestExtractJsonObject:
    def test_simple_object(self):
        result = _extract_json_object('{"action": "quiz", "message": "hi"}')
        assert result == {"action": "quiz", "message": "hi"}

    def test_nested_object(self):
        text = '{"action": "add_concept", "params": {"title": "Test"}, "message": "ok"}'
        result = _extract_json_object(text)
        assert result["action"] == "add_concept"
        assert result["params"]["title"] == "Test"
        assert result["message"] == "ok"

    def test_no_json(self):
        assert _extract_json_object("just plain text") is None

    def test_empty_string(self):
        assert _extract_json_object("") is None

    def test_text_before_json(self):
        text = 'Some preamble {"action": "quiz", "message": "hi"}'
        result = _extract_json_object(text)
        assert result["action"] == "quiz"

    def test_text_after_json(self):
        text = '{"action": "quiz", "message": "hi"} trailing text'
        result = _extract_json_object(text)
        assert result["action"] == "quiz"
        assert result["message"] == "hi"

    def test_malformed_json_returns_none(self):
        assert _extract_json_object('{"action": "quiz", trailing,}') is None


# ============================================================================
# _extract_json_object — braces in string values (the bug)
# ============================================================================

class TestExtractJsonObjectBracesInStrings:
    """The core bug: braces inside JSON string values (C++, LaTeX, etc.)
    caused the old brace-counting approach to fail."""

    def test_cpp_code_in_message(self):
        """The exact trigger: C++ code with curly braces in the message field."""
        obj = {
            "action": "add_concept",
            "params": {"title": "C++ Templates"},
            "message": "Here is code: int f() { return 1; } done"
        }
        text = json.dumps(obj)
        result = _extract_json_object(text)
        assert result is not None
        assert result["action"] == "add_concept"
        assert "{ return 1; }" in result["message"]

    def test_multiple_cpp_blocks(self):
        obj = {
            "action": "quiz",
            "message": "Compare: void a() { x++; } vs void b() { y--; }"
        }
        text = json.dumps(obj)
        result = _extract_json_object(text)
        assert result is not None
        assert result["action"] == "quiz"

    def test_latex_braces(self):
        obj = {
            "action": "add_concept",
            "message": "The formula is \\frac{a}{b} + \\sum_{i=0}^{n} x_i"
        }
        text = json.dumps(obj)
        result = _extract_json_object(text)
        assert result is not None
        assert result["action"] == "add_concept"

    def test_regex_braces(self):
        obj = {
            "action": "quiz",
            "message": "What does [a-z]{3,5} match?"
        }
        text = json.dumps(obj)
        result = _extract_json_object(text)
        assert result is not None

    def test_json_example_in_description(self):
        """JSON with escaped quotes and braces nested inside a string value."""
        obj = {
            "action": "add_concept",
            "params": {"description": 'Use format {"key": "value"} for config'},
            "message": "Added concept."
        }
        text = json.dumps(obj)
        result = _extract_json_object(text)
        assert result is not None
        assert result["message"] == "Added concept."

    def test_python_dict_in_message(self):
        obj = {
            "action": "quiz",
            "message": "What does {'a': 1, 'b': 2} represent?"
        }
        text = json.dumps(obj)
        result = _extract_json_object(text)
        assert result is not None

    def test_deeply_nested_code_blocks(self):
        obj = {
            "action": "add_concept",
            "message": "```cpp\ntemplate<typename T>\nstruct Foo {\n    T bar() { return T{}; }\n};\n```"
        }
        text = json.dumps(obj)
        result = _extract_json_object(text)
        assert result is not None
        assert result["action"] == "add_concept"
        assert "template<typename T>" in result["message"]


# ============================================================================
# _extract_json_object — last-valid-parse (not first-valid)
# ============================================================================

class TestExtractJsonObjectLastValid:
    """Verify we get the COMPLETE object, not a partial one."""

    def test_partial_vs_complete(self):
        """Inner sub-object is valid JSON, but we want the full outer object."""
        obj = {
            "action": "add_concept",
            "params": {"title": "Test"},
            "message": "Full explanation here"
        }
        text = json.dumps(obj)
        result = _extract_json_object(text)
        # Must have ALL fields, not just action + params
        assert "message" in result
        assert result["message"] == "Full explanation here"

    def test_nested_valid_json_returns_outermost(self):
        """When params contains a nested dict, don't stop at params' closing brace."""
        text = '{"action": "x", "params": {"a": {"b": 1}}, "message": "done"}'
        result = _extract_json_object(text)
        assert result["message"] == "done"


# ============================================================================
# _extract_json_str
# ============================================================================

class TestExtractJsonStr:
    def test_simple(self):
        text = '{"action": "quiz", "message": "hi"}'
        result = _extract_json_str(text)
        assert result is not None
        assert json.loads(result) == {"action": "quiz", "message": "hi"}

    def test_cpp_code_in_string(self):
        obj = {"action": "quiz", "message": "void f() { return; }"}
        text = json.dumps(obj)
        result = _extract_json_str(text)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["message"] == "void f() { return; }"

    def test_returns_none_for_no_json(self):
        assert _extract_json_str("no json here") is None

    def test_with_trailing_text(self):
        text = '{"action": "quiz"} some extra text'
        result = _extract_json_str(text)
        assert result is not None
        assert json.loads(result) == {"action": "quiz"}


# ============================================================================
# extract_fetch_params (refactored to use _extract_json_object)
# ============================================================================

class TestExtractFetchParams:
    def test_code_block_fetch(self):
        response = '```json\n{"action": "fetch", "params": {"topic_id": 3}}\n```'
        result = extract_fetch_params(response)
        assert result == {"topic_id": 3}

    def test_bare_fetch(self):
        response = '{"action": "fetch", "params": {"concept_id": 7}, "message": "Loading..."}'
        result = extract_fetch_params(response)
        assert result == {"concept_id": 7}

    def test_non_fetch_returns_none(self):
        response = '{"action": "quiz", "params": {"concept_id": 5}}'
        assert extract_fetch_params(response) is None

    def test_no_json_returns_none(self):
        assert extract_fetch_params("REPLY: hello") is None

    def test_fetch_with_code_in_strings(self):
        """Fetch with code in surrounding text shouldn't break extraction."""
        response = 'Here is code { int x; } and {"action": "fetch", "params": {"topic_id": 1}}'
        result = extract_fetch_params(response)
        assert result == {"topic_id": 1}


# ============================================================================
# parse_llm_response — end-to-end
# ============================================================================

class TestParseLlmResponse:
    def test_reply_prefix(self):
        prefix, msg, data = parse_llm_response("REPLY: hello world")
        assert prefix == "REPLY"
        assert msg == "hello world"
        assert data is None

    def test_json_code_block(self):
        response = '```json\n{"action": "quiz", "params": {"concept_id": 5}, "message": "Question?"}\n```'
        prefix, msg, data = parse_llm_response(response)
        assert prefix == "ACTION"
        assert data["action"] == "quiz"
        assert msg == "Question?"

    def test_bare_json(self):
        response = '{"action": "add_concept", "params": {"title": "X"}, "message": "Added X."}'
        prefix, msg, data = parse_llm_response(response)
        assert prefix == "ACTION"
        assert data["action"] == "add_concept"

    def test_json_with_cpp_code_in_message(self):
        """The exact failure scenario from the bug report."""
        obj = {
            "action": "add_concept",
            "params": {"title": "C++ Templates", "topic_ids": [37]},
            "message": "Good call — C++ Templates added.\nQuick intuition: template<typename T> T max(T a, T b) { return a > b ? a : b; }\nNow back to decorators — what does [f](int x) capture? 🧠"
        }
        response = json.dumps(obj)
        prefix, msg, data = parse_llm_response(response)
        assert prefix == "ACTION", f"Expected ACTION, got {prefix}"
        assert data is not None, "action_data should not be None"
        assert data["action"] == "add_concept"
        assert "{ return a > b ? a : b; }" in data["message"]

    def test_fallback_to_reply(self):
        prefix, msg, data = parse_llm_response("just some text")
        assert prefix == "REPLY"
        assert msg == "just some text"
        assert data is None


# ============================================================================
# process_output — safety net
# ============================================================================

class TestProcessOutput:
    def test_reply_prefix(self):
        assert process_output("REPLY: hello") == ("reply", "hello")

    def test_review_prefix(self):
        assert process_output("REVIEW: quiz time") == ("review", "quiz time")

    def test_no_prefix_plain_text(self):
        assert process_output("just text") == ("reply", "just text")

    def test_empty_returns_no_response(self):
        assert process_output("") == ("reply", "No response.")

    def test_safety_net_extracts_message_from_json(self):
        """If raw JSON leaks through, extract the message field."""
        raw = '{"action": "add_concept", "params": {}, "message": "Here is your answer."}'
        msg_type, msg = process_output(raw)
        assert msg_type == "reply"
        assert msg == "Here is your answer."

    def test_safety_net_with_cpp_braces(self):
        """Safety net must handle JSON with code-braces in message."""
        obj = {
            "action": "quiz",
            "message": "What does void f() { return; } do?"
        }
        raw = json.dumps(obj)
        msg_type, msg = process_output(raw)
        assert msg_type == "reply"
        assert "{ return; }" in msg

    def test_safety_net_ignores_non_action_json(self):
        """Plain JSON without 'action' key should pass through as-is."""
        raw = '{"name": "test", "value": 42}'
        msg_type, msg = process_output(raw)
        assert msg_type == "reply"
        assert msg == raw

    def test_prefixed_reply_with_json_not_intercepted(self):
        """REPLY: prefix takes priority over safety net."""
        text = 'REPLY: {"action": "quiz", "message": "hi"}'
        msg_type, msg = process_output(text)
        assert msg_type == "reply"
        assert msg == '{"action": "quiz", "message": "hi"}'
