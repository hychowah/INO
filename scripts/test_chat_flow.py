#!/usr/bin/env python3
"""Manual chat-flow harness for exercising the real conversation pipeline.

This script drives the same chat entrypoint used by the web/API chat surface,
so you can emulate multi-turn flows like:

- /learn conversations
- /review followed by one or more synthetic answers
- repeated follow-ups after a quiz or clarification turn

By default it copies the current databases into a sandbox directory and runs
against those copies, so transcript debugging does not mutate live history.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "scripts" / "prompt_logs"
SEP = "=" * 72
SEP_THIN = "-" * 72


def _configure_stdio() -> None:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _ensure_repo_on_path() -> None:
    root = str(ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _bootstrap_storage(argv: list[str]) -> dict[str, Any]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--live-db", action="store_true")
    parser.add_argument("--sandbox-dir")
    args, _unknown = parser.parse_known_args(argv)

    os.environ.setdefault("LEARN_DISABLE_VECTOR_SYNC", "1")

    if args.live_db:
        return {"mode": "live"}

    sandbox_dir = (
        Path(args.sandbox_dir).expanduser().resolve()
        if args.sandbox_dir
        else Path(tempfile.mkdtemp(prefix="learn_flow_"))
    )
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    knowledge_src = DATA_DIR / "knowledge.db"
    chat_src = DATA_DIR / "chat_history.db"
    knowledge_dst = sandbox_dir / "knowledge.db"
    chat_dst = sandbox_dir / "chat_history.db"

    if knowledge_src.exists():
        shutil.copy2(knowledge_src, knowledge_dst)
    if chat_src.exists():
        shutil.copy2(chat_src, chat_dst)

    os.environ["LEARN_DB_PATH"] = str(knowledge_dst)
    os.environ["LEARN_CHAT_DB_PATH"] = str(chat_dst)

    return {
        "mode": "sandbox",
        "sandbox_dir": str(sandbox_dir),
        "knowledge_db": str(knowledge_dst),
        "chat_db": str(chat_dst),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a scripted conversation through the real chat pipeline.",
    )
    parser.add_argument(
        "--scenario",
        choices=("review",),
        help="Built-in flow seed. 'review' starts with /review.",
    )
    parser.add_argument(
        "--answer",
        action="append",
        default=[],
        help="Synthetic user reply appended after a built-in scenario. Repeatable.",
    )
    parser.add_argument(
        "--turn",
        action="append",
        default=[],
        help="Literal user message to send. Repeat in chronological order.",
    )
    parser.add_argument(
        "--author",
        default="flow-harness",
        help="Display name passed into the chat pipeline.",
    )
    parser.add_argument(
        "--user-id",
        default="default",
        help="Scoped user id for DB reads/writes. Defaults to the legacy single-user id.",
    )
    parser.add_argument(
        "--source",
        default="flow-harness",
        help="Action source label recorded in action logs.",
    )
    parser.add_argument(
        "--history-limit",
        type=int,
        default=4,
        help="How many recent chat messages to include per turn when --show-history is enabled.",
    )
    parser.add_argument(
        "--show-history",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Print the recent chat history after each turn.",
    )
    parser.add_argument(
        "--log",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write a JSON transcript log under scripts/prompt_logs.",
    )
    parser.add_argument(
        "--log-file",
        help="Optional explicit path for the JSON transcript log.",
    )
    parser.add_argument(
        "--list-due",
        action="store_true",
        help="List due concepts for the selected DB/user scope, then exit.",
    )
    parser.add_argument(
        "--live-db",
        action="store_true",
        help="Run against data/knowledge.db and data/chat_history.db directly.",
    )
    parser.add_argument(
        "--sandbox-dir",
        help="Optional directory for sandboxed DB copies. Ignored with --live-db.",
    )
    return parser


def expand_turns(args: argparse.Namespace) -> list[str]:
    turns: list[str] = []

    if args.scenario == "review":
        turns.append("/review")
        turns.extend(args.answer)
    elif args.answer:
        raise ValueError("--answer requires --scenario review")

    turns.extend(args.turn)

    return [turn for turn in turns if str(turn).strip()]


def summarize_actions(actions: list[dict] | None) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for action in actions or []:
        action_type = action.get("type", "unknown")
        if action_type == "multiple_choice":
            summaries.append(
                {
                    "type": action_type,
                    "title": action.get("title"),
                    "choices": [choice.get("label") for choice in action.get("choices", [])],
                }
            )
            continue
        if action_type == "button_group":
            summaries.append(
                {
                    "type": action_type,
                    "title": action.get("title"),
                    "buttons": [button.get("label") for button in action.get("buttons", [])],
                }
            )
            continue
        if action_type == "proposal_review":
            summaries.append(
                {
                    "type": action_type,
                    "title": action.get("title"),
                    "items": [item.get("label") for item in action.get("items", [])],
                }
            )
            continue
        summaries.append(action)
    return summaries


def _snapshot_state() -> dict[str, Any]:
    _ensure_repo_on_path()

    import db
    from services.review_state import get_pending_review

    return {
        "active_concept_id": db.get_session("active_concept_id"),
        "active_concept_ids": db.get_session("active_concept_ids"),
        "quiz_anchor_concept_id": db.get_session("quiz_anchor_concept_id"),
        "last_quiz_question": db.get_session("last_quiz_question"),
        "quiz_answered": db.get_session("quiz_answered"),
        "review_in_progress": db.get_session("review_in_progress"),
        "pending_review": get_pending_review(),
    }


def _history_tail(limit: int) -> list[dict[str, Any]]:
    _ensure_repo_on_path()

    import db

    history = db.get_chat_history(limit=limit)
    return [{"role": item.get("role"), "content": item.get("content")} for item in history]


def _print_header(args: argparse.Namespace, storage: dict[str, Any], turns: list[str]) -> None:
    print(SEP)
    print("CHAT FLOW HARNESS")
    print(SEP)
    print(f"Scenario   : {args.scenario or 'custom'}")
    print(f"Turns      : {len(turns)}")
    print(f"User scope : {args.user_id}")
    print(f"Author     : {args.author}")
    print(f"Source     : {args.source}")
    if storage.get("mode") == "sandbox":
        print(f"Storage    : sandbox ({storage['sandbox_dir']})")
    else:
        print("Storage    : live data directory")
    print(SEP_THIN)


def _print_turn(entry: dict[str, Any], show_history: bool) -> None:
    response = entry["response"]
    print(f"\n{SEP}")
    print(f"TURN {entry['turn']}")
    print(SEP)
    print(f"USER    : {entry['user_message']}")
    print(f"TYPE    : {response.get('type')}")
    print(f"LATENCY : {entry['duration_ms']} ms")
    print(f"\nASSISTANT\n{SEP_THIN}")
    print(response.get("message", ""))

    if response.get("pending_action"):
        print(f"\nPENDING ACTION\n{SEP_THIN}")
        print(json.dumps(response["pending_action"], indent=2, ensure_ascii=False))

    if entry["action_summary"]:
        print(f"\nACTION SUMMARY\n{SEP_THIN}")
        print(json.dumps(entry["action_summary"], indent=2, ensure_ascii=False))

    print(f"\nSTATE SNAPSHOT\n{SEP_THIN}")
    print(json.dumps(entry["state"], indent=2, ensure_ascii=False, default=str))

    if show_history:
        print(f"\nRECENT CHAT HISTORY\n{SEP_THIN}")
        print(json.dumps(entry["history_tail"], indent=2, ensure_ascii=False, default=str))


def _write_log(payload: dict[str, Any], log_file: str | None = None) -> Path:
    target = Path(log_file).expanduser().resolve() if log_file else None
    if target is None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = LOG_DIR / f"chat_flow_{stamp}.json"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def _print_due_concepts(user_id: str) -> None:
    _ensure_repo_on_path()

    import db
    import db.core as db_core
    from services import state

    db_core._init_vector_store = lambda: None

    with state.current_user_scope(user_id):
        due = db.get_due_concepts(limit=10)

    if not due:
        print("No concepts due for review.")
        return

    print(f"\n{'ID':>5}  {'Score':>5}  {'Reviews':>7}  Title")
    print(SEP_THIN)
    for concept in due:
        print(
            f"{concept['id']:>5}  {concept['mastery_level']:>5}  "
            f"{concept['review_count']:>7}  {concept['title']}"
        )


async def _run_flow(args: argparse.Namespace, storage: dict[str, Any]) -> tuple[list[dict], Path | None]:
    _ensure_repo_on_path()

    import db
    import db.core as db_core
    from services import chat_session, state

    turns = expand_turns(args)
    if not turns:
        raise ValueError("Provide at least one --turn, or use --scenario review.")

    db_core._init_vector_store = lambda: None
    db.init_databases()
    _print_header(args, storage, turns)

    transcript: list[dict[str, Any]] = []
    with state.current_user_scope(args.user_id):
        for index, turn in enumerate(turns, start=1):
            started_at = datetime.now().isoformat(timespec="seconds")
            started = perf_counter()
            payload = await chat_session.handle_chat_message(
                turn,
                author=args.author,
                source=args.source,
            )
            duration_ms = round((perf_counter() - started) * 1000, 1)
            entry = {
                "turn": index,
                "started_at": started_at,
                "user_message": turn,
                "duration_ms": duration_ms,
                "response": payload,
                "action_summary": summarize_actions(payload.get("actions")),
                "state": _snapshot_state(),
                "history_tail": _history_tail(args.history_limit) if args.show_history else [],
            }
            transcript.append(entry)
            _print_turn(entry, args.show_history)

    log_path = None
    if args.log:
        log_payload = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "args": {
                "scenario": args.scenario,
                "turns": turns,
                "author": args.author,
                "user_id": args.user_id,
                "source": args.source,
                "show_history": args.show_history,
                "history_limit": args.history_limit,
            },
            "storage": storage,
            "transcript": transcript,
        }
        log_path = _write_log(log_payload, args.log_file)

    return transcript, log_path


async def async_main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    storage = _bootstrap_storage(argv)
    _ensure_repo_on_path()

    import db
    import db.core as db_core

    args = build_arg_parser().parse_args(argv)
    db_core._init_vector_store = lambda: None
    db.init_databases()

    if args.list_due:
        _print_due_concepts(args.user_id)
        return 0

    _transcript, log_path = await _run_flow(args, storage)

    if log_path is not None:
        print(f"\n{SEP_THIN}")
        print(f"JSON transcript written to: {log_path}")
        print(SEP_THIN)

    return 0


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    try:
        return asyncio.run(async_main(argv))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())