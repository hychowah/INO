# Chat Flow Harness

Use [scripts/test_chat_flow.py](scripts/test_chat_flow.py) when you want to drive the real chat pipeline through a scripted multi-turn conversation and inspect what the assistant actually returned at each step.

What it does:
- Sends turns through [services/chat_session.py](services/chat_session.py), which is the same chat entrypoint used by the web/API surface.
- Prints each user turn, assistant message, message type, action summary, and the active quiz/review session state after the turn.
- Saves a JSON transcript under `scripts/prompt_logs/` so you can diff runs or inspect them later.
- Defaults to a sandbox copy of `data/knowledge.db` and `data/chat_history.db`, so review/debug runs do not mutate your live history.

Basic usage:

```bash
python scripts/test_chat_flow.py --turn "/learn What is GraphRAG?"
python scripts/test_chat_flow.py --scenario review --answer "induced drag is cut in half"
python scripts/test_chat_flow.py --scenario review --answer "global search for sector trends" --answer "local search for Company X"
```

Useful options:
- `--scenario review`: starts the flow with `/review`.
- `--answer "..."`: appends one or more synthetic user replies after a built-in scenario.
- `--turn "..."`: append any literal user turn. Repeat to build a longer transcript.
- `--show-history`: include the recent chat history after each turn.
- `--list-due`: print due concepts for the selected DB/user scope, then exit.
- `--live-db`: run against the real `data/*.db` files instead of a sandbox copy.
- `--sandbox-dir PATH`: keep the sandbox DB copy in a predictable directory.
- `--user-id default`: keep this unless you specifically need to test a different scoped user.
- `--log-file PATH`: write the JSON transcript to a custom path.

Recommended review-flow loop:

```bash
python scripts/test_chat_flow.py \
  --scenario review \
  --answer "when asking about sector, use global search with community summaries" \
  --answer "for Company X inside that sector, use local search on the relevant nodes"
```

That gives you a turn-by-turn trace showing:
- the generated review question
- the assistant's response to each synthetic answer
- whether the pipeline treated the follow-up as quiz handling or casual chat
- the live quiz state (`quiz_anchor_concept_id`, `last_quiz_question`, pending reminder)

Notes:
- The harness does not auto-score quality for you. It exposes the transcript, actions, and state so you can inspect whether the flow quality is acceptable.
- Because it runs the real pipeline, it uses your configured LLM provider and consumes real tokens.
- Sandbox mode copies the current DB files first, so the script sees your current concepts and due reviews without changing the live DB.