"""
LLM response parsing and output classification.

Consolidated from pipeline.py and agent.py — single source of truth
for response format handling.
"""

import re
import json


# ============================================================================
# LLM Response Parsing
# ============================================================================

def parse_llm_response(response: str) -> tuple:
    """
    Parse LLM response to extract (prefix, message, action_data).
    Returns: (prefix, message, action_dict or None)

    Prefixes: REPLY, ASK, REMINDER, REVIEW, ACTION
    """
    response = response.strip()

    for prefix in ('REPLY:', 'ASK:', 'REMINDER:', 'REVIEW:'):
        if response.startswith(prefix):
            return (prefix[:-1], response[len(prefix):].strip(), None)

    # Try ```json code block
    code_block_match = re.search(r'```json\s*\n?([\s\S]*?)\n?\s*```', response)
    if code_block_match:
        block_content = code_block_match.group(1).strip()
        json_obj = _extract_json_object(block_content)
        if json_obj:
            return ("ACTION", json_obj.get("message", ""), json_obj)

    # Try bare JSON with "action" key
    bare_match = re.search(r'\{\s*"action"', response)
    if bare_match:
        json_obj = _extract_json_object(response[bare_match.start():])
        if json_obj:
            return ("ACTION", json_obj.get("message", ""), json_obj)

    # Default: treat as REPLY
    return ("REPLY", response, None)


def _extract_json_object(text: str) -> dict | None:
    """Extract the first complete JSON object via brace counting."""
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:]):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:start + i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# ============================================================================
# Fetch Extraction
# ============================================================================

def extract_fetch_params(response: str) -> dict | None:
    """Check if an LLM response is a fetch action. Returns params dict or None."""
    code_block = re.search(r"```json\s*\n?([\s\S]*?)\n?\s*```", response)
    if code_block:
        try:
            data = json.loads(code_block.group(1).strip())
            if data.get("action", "").lower() == "fetch":
                return data.get("params", {})
        except json.JSONDecodeError:
            pass

    bare = re.search(r'\{\s*"action"\s*:\s*"fetch"', response, re.IGNORECASE)
    if bare:
        start = bare.start()
        depth = 0
        for i, ch in enumerate(response[start:]):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(response[start:start + i + 1])
                        if data.get("action", "").lower() == "fetch":
                            return data.get("params", {})
                    except json.JSONDecodeError:
                        pass
                    break
    return None


# ============================================================================
# Output Extraction & Classification
# ============================================================================

def extract_llm_action(output: str) -> str:
    """Extract the actual action/response from LLM output.
    The LLM may echo back the entire prompt, so we search from the end."""
    if not output:
        return ""

    # Pattern 1: JSON in ```json code block (last one)
    json_blocks = list(re.finditer(r"```json\s*\n?([\s\S]*?)\n?\s*```", output))
    for block in reversed(json_blocks):
        content = block.group(1).strip()
        j = content.find("{")
        if j != -1:
            obj = _extract_json_str(content[j:])
            if obj is not None:
                return obj

    # Pattern 2: Bare JSON with "action" (last valid one)
    for m in reversed(list(re.finditer(r'\{\s*"action"\s*:', output))):
        obj = _extract_json_str(output[m.start():])
        if obj is not None:
            return obj

    # Pattern 3: Prefix lines (last occurrence)
    for prefix in ("REVIEW:", "REPLY:", "ASK:"):
        starts = [
            m.start()
            for m in re.finditer(rf"^{re.escape(prefix)}\s*", output, re.MULTILINE)
        ]
        if starts:
            return output[starts[-1]:].strip()

    # Pattern 4: After "## Your Response" marker
    marker = "## Your Response"
    if marker in output:
        parts = output.split(marker)
        if len(parts) > 1:
            tail = parts[-1].strip()
            if tail:
                return tail

    # Fallback: last non-empty chunk
    lines = [l for l in output.strip().split("\n") if l.strip()]
    if lines:
        return "\n".join(lines[-20:])
    return output


def _extract_json_str(text: str) -> str | None:
    """Extract the first complete JSON object string via brace counting."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:]):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:start + i + 1]
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    return None
    return None


def process_output(output: str) -> tuple[str, str]:
    """Classify agent output by prefix.
    Returns (msg_type, message). msg_type: 'reply', 'ask', 'review', 'prompt', 'error'."""
    if not output:
        return ("reply", "No response.")

    for prefix, mtype in [
        ("PROMPT:", "prompt"),
        ("REPLY:", "reply"),
        ("ASK:", "ask"),
        ("REVIEW:", "review"),
        ("FETCH:", "fetch"),
    ]:
        if output.startswith(prefix):
            return (mtype, output[len(prefix):].strip())

    return ("reply", output)
