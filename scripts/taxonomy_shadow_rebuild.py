#!/usr/bin/env python3
"""Preview and apply a taxonomy reconstruction using shadow data copies.

Preview runs taxonomy mode against temporary SQLite/vector-store copies in a
separate process, then live apply replays the recorded safe actions after an
immediate backup.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_MAX_ACTIONS = 75
DEFAULT_CONTINUATION_CONTEXT_LIMIT = 12000
DEFAULT_STRUCTURE_DIR = ROOT / "backups" / "taxonomy_shadow_rebuild"
DEFAULT_STRUCTURE_FORMAT = "md"
AGGRESSIVE_OPERATOR_DIRECTIVE = """This is an explicit administrator-requested reconstruction pass, not a routine weekly tidy-up.

Be aggressive within the existing taxonomy rules:
- Prefer making high-value structural changes rather than preserving the status quo.
- Actively look for root topics that should be grouped, even if the tree is merely acceptable today.
- If a topic obviously fits under an existing parent, reparent it.
- If no action seems obvious from the tree alone, use fetch to inspect the strongest candidates before concluding no change is needed.
- Use the full action budget on meaningful structural improvements before deciding the taxonomy is already optimal.

Do not violate the skill constraints, but do bias toward proposing or executing a real reconstruction when there is a defensible case."""


def _configure_stdio() -> None:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _resolve_repo_path(env_name: str, default_rel: str) -> Path:
    raw = os.environ.get(env_name)
    if not raw:
        return ROOT / default_rel
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path


def _live_store_paths() -> dict[str, Path]:
    return {
        "knowledge_db": _resolve_repo_path("LEARN_DB_PATH", "data/knowledge.db"),
        "chat_db": _resolve_repo_path("LEARN_CHAT_DB_PATH", "data/chat_history.db"),
        "vectors_dir": _resolve_repo_path("LEARN_VECTOR_STORE_PATH", "data/vectors"),
    }


def _copy_sqlite(src_path: Path, dest_path: Path) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if not src_path.exists():
        return

    src_conn = sqlite3.connect(src_path)
    try:
        dst_conn = sqlite3.connect(dest_path)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def _copy_vectors(src_dir: Path, dest_dir: Path) -> None:
    if not src_dir.exists():
        return
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(src_dir, dest_dir)


def _create_shadow_workspace(base_dir: Path) -> dict[str, Path]:
    base_dir.mkdir(parents=True, exist_ok=True)
    shadow = {
        "knowledge_db": base_dir / "knowledge.db",
        "chat_db": base_dir / "chat_history.db",
        "vectors_dir": base_dir / "vectors",
    }
    live = _live_store_paths()
    _copy_sqlite(live["knowledge_db"], shadow["knowledge_db"])
    _copy_sqlite(live["chat_db"], shadow["chat_db"])
    _copy_vectors(live["vectors_dir"], shadow["vectors_dir"])
    return shadow


def _topic_map_signature(topic_map: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "id": item["id"],
                "title": item["title"],
                "description": item.get("description"),
                "concept_count": item.get("concept_count", 0),
                "parent_ids": sorted(item.get("parent_ids", [])),
                "child_ids": sorted(item.get("child_ids", [])),
            }
            for item in topic_map
        ],
        key=lambda item: item["id"],
    )


def _topic_map_summary(topic_map: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "topics": len(topic_map),
        "root_topics": sum(1 for item in topic_map if not item.get("parent_ids")),
        "edges": sum(len(item.get("child_ids", [])) for item in topic_map),
        "concept_links": sum(item.get("concept_count", 0) for item in topic_map),
    }


def _format_summary(summary: dict[str, int]) -> str:
    return (
        f"topics={summary['topics']}, roots={summary['root_topics']}, "
        f"edges={summary['edges']}, concept_links={summary['concept_links']}"
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_output_dir(path_str: str | None) -> Path:
    if not path_str:
        return DEFAULT_STRUCTURE_DIR
    path = Path(path_str)
    if not path.is_absolute():
        path = ROOT / path
    return path


def _looks_like_onedrive_path(path: Path) -> bool:
    return "onedrive" in str(path).lower()


def _render_topic_tree_lines(topic_map: list[dict[str, Any]]) -> list[str]:
    children: dict[int, list[int]] = {}
    topic_by_id: dict[int, dict[str, Any]] = {item["id"]: item for item in topic_map}
    for item in topic_map:
        for child_id in sorted(item.get("child_ids", [])):
            children.setdefault(item["id"], []).append(child_id)

    root_ids = sorted(item["id"] for item in topic_map if not item.get("parent_ids"))
    visited: set[int] = set()
    lines: list[str] = []

    def _walk(node_id: int, depth: int) -> None:
        if node_id in visited:
            return
        visited.add(node_id)
        topic = topic_by_id.get(node_id)
        if not topic:
            return
        indent = "  " * depth
        lines.append(
            f"{indent}[topic:{topic['id']}] {topic['title']} ({topic.get('concept_count', 0)} concepts)"
        )
        for child_id in children.get(node_id, []):
            _walk(child_id, depth + 1)

    for root_id in root_ids:
        _walk(root_id, 0)

    for item in sorted(topic_map, key=lambda topic: topic["id"]):
        if item["id"] not in visited:
            lines.append(
                f"⚠️ [topic:{item['id']}] {item['title']} ({item.get('concept_count', 0)} concepts) [orphaned]"
            )

    if not lines:
        lines.append("No topics yet.")
    return lines


def _render_structure_document(
    *,
    title: str,
    summary: dict[str, int],
    topic_map: list[dict[str, Any]],
    fmt: str,
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tree_lines = _render_topic_tree_lines(topic_map)
    summary_line = _format_summary(summary)

    if fmt == "txt":
        parts = [
            title,
            f"Generated: {generated_at}",
            f"Summary: {summary_line}",
            "",
            "Full Topic Tree",
            *tree_lines,
            "",
        ]
        return "\n".join(parts)

    body = "\n".join(tree_lines)
    return (
        f"# {title}\n\n"
        f"Generated: {generated_at}\n\n"
        f"Summary: {summary_line}\n\n"
        "## Full Topic Tree\n\n"
        "```text\n"
        f"{body}\n"
        "```\n"
    )


def _write_structure_snapshot(
    *,
    output_dir: Path,
    run_stamp: str,
    label: str,
    fmt: str,
    summary: dict[str, int],
    topic_map: list[dict[str, Any]],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = fmt
    latest_path = output_dir / f"{label}_latest.{suffix}"
    stamped_path = output_dir / f"{run_stamp}_{label}.{suffix}"
    title = label.replace("_", " ").title()
    document = _render_structure_document(
        title=title,
        summary=summary,
        topic_map=topic_map,
        fmt=fmt,
    )
    latest_path.write_text(document, encoding="utf-8")
    stamped_path.write_text(document, encoding="utf-8")
    return latest_path, stamped_path


def _looks_like_action_error(result: str) -> bool:
    return "⚠️" in result or result.startswith("REPLY: ⚠") or result.startswith("⚠")


def _replayable_entries(action_journal: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry for entry in action_journal if entry.get("replayable")]


async def replay_action_journal(
    action_journal: list[dict[str, Any]],
    *,
    execute_action,
    get_created_topic_id,
) -> list[dict[str, Any]]:
    replay_results = []

    for entry in _replayable_entries(action_journal):
        action_name = entry["action"]
        result = await execute_action(entry["action_data"])
        replay_entry = {
            "step": entry["step"],
            "action": action_name,
            "result": result,
        }

        if _looks_like_action_error(result):
            raise RuntimeError(f"Replay failed at step {entry['step']} ({action_name}): {result}")

        if action_name == "add_topic":
            actual_topic_id = get_created_topic_id()
            replay_entry["created_topic_id"] = actual_topic_id
            expected_topic_id = entry.get("created_topic_id")
            if str(actual_topic_id) != str(expected_topic_id):
                raise RuntimeError(
                    "Topic ID mismatch during replay at step "
                    f"{entry['step']}: expected {expected_topic_id}, got {actual_topic_id}"
                )

        replay_results.append(replay_entry)

    return replay_results


def _ensure_project_imports() -> None:
    root_str = str(ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def _init_databases_without_vector_bootstrap() -> None:
    """Initialize SQLite schema and migrations without eagerly loading vectors.

    The rebuild script only needs the embedded vector store if taxonomy actions
    actually write new topic embeddings. Skipping db.init_databases() avoids an
    unconditional sentence-transformers model load during startup.
    """
    import db.core as db_core

    db_core.DATA_DIR.mkdir(parents=True, exist_ok=True)
    db_core.KNOWLEDGE_DB.parent.mkdir(parents=True, exist_ok=True)
    db_core.CHAT_DB.parent.mkdir(parents=True, exist_ok=True)
    db_core._init_knowledge_db()
    db_core._init_chat_db()
    db_core._run_migrations()


async def _preview_internal(args: argparse.Namespace) -> int:
    _ensure_project_imports()

    import db
    import db.vectors
    from services.pipeline import call_taxonomy_loop, handle_taxonomy

    try:
        _init_databases_without_vector_bootstrap()
        before_map = db.get_topic_map()
        taxonomy_context = handle_taxonomy()

        action_journal: list[dict[str, Any]] = []
        proposed_actions: list[dict[str, Any]] = []
        report_text = "REPLY: No topics found."

        if taxonomy_context is not None:
            report_text, proposed_actions = await call_taxonomy_loop(
                taxonomy_context,
                max_actions=args.max_actions,
                continuation_context_limit=args.continuation_context_limit,
                action_journal=action_journal,
                operator_directive=(AGGRESSIVE_OPERATOR_DIRECTIVE if args.aggressive else None),
            )

        after_map = db.get_topic_map()
        payload = {
            "no_topics": taxonomy_context is None,
            "report_text": report_text,
            "action_journal": action_journal,
            "proposed_actions": proposed_actions,
            "before_topic_map": before_map,
            "after_topic_map": after_map,
            "before_summary": _topic_map_summary(before_map),
            "after_summary": _topic_map_summary(after_map),
            "before_signature": _topic_map_signature(before_map),
            "after_signature": _topic_map_signature(after_map),
        }
        _write_json(Path(args.result_file), payload)

        print("[preview] complete")
        print(f"[preview] before: {_format_summary(payload['before_summary'])}")
        print(f"[preview] after:  {_format_summary(payload['after_summary'])}")
        print(f"[preview] safe actions recorded: {len(_replayable_entries(action_journal))}")
        print(f"[preview] approval-gated actions: {len(proposed_actions)}")
        return 0
    finally:
        db.vectors.close_client()


async def _apply_internal(args: argparse.Namespace) -> int:
    preview = _read_json(Path(args.preview_file))
    _ensure_project_imports()

    import db
    import db.vectors
    import config
    from services import tools
    from services.backup import perform_backup
    from services.pipeline import execute_action

    try:
        _init_databases_without_vector_bootstrap()
        current_map = db.get_topic_map()
        current_signature = _topic_map_signature(current_map)

        if current_signature != preview["before_signature"]:
            print("[apply] live taxonomy no longer matches the preview baseline; aborting.")
            return 2

        try:
            backup_path = perform_backup()
        except PermissionError as exc:
            backup_dir = config.BACKUP_DIR
            print(f"[apply] backup failed: {exc}")
            print(
                "[apply] This is usually a Windows file-lock issue, not an admin-rights issue."
            )
            if _looks_like_onedrive_path(backup_dir):
                print(
                    "[apply] The backup directory is inside OneDrive, which commonly grabs fresh "
                    "files during rename/copy operations."
                )
            print(
                "[apply] Retry after pausing OneDrive sync or set LEARN_BACKUP_DIR to a local "
                "folder outside OneDrive, then rerun the script."
            )
            return 4
        print(f"[apply] backup saved: {backup_path}")

        tools.set_action_source("taxonomy")

        replay_results = await replay_action_journal(
            preview["action_journal"],
            execute_action=execute_action,
            get_created_topic_id=lambda: db.get_session("last_added_topic_id"),
        )

        final_map = db.get_topic_map()
        final_signature = _topic_map_signature(final_map)
        if final_signature != preview["after_signature"]:
            print("[apply] replay completed, but final taxonomy does not match preview output.")
            return 3

        print(f"[apply] replayed safe actions: {len(replay_results)}")
        proposed_actions = preview.get("proposed_actions", [])
        if proposed_actions:
            print(f"[apply] approval-gated actions still pending: {len(proposed_actions)}")
            for index, action in enumerate(proposed_actions, start=1):
                print(f"  [{index}] {action.get('action', '?')} — {action.get('message', '')[:120]}")
        return 0
    finally:
        db.vectors.close_client()


def _run_child(args: list[str], env: dict[str, str]) -> int:
    cmd = [sys.executable, str(SCRIPT_PATH), *args]
    completed = subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)
    return completed.returncode


def _print_preview(payload: dict[str, Any]) -> None:
    print("\n=== Preview Summary ===")
    print(f"Before: {_format_summary(payload['before_summary'])}")
    print(f"After:  {_format_summary(payload['after_summary'])}")

    replayable = _replayable_entries(payload["action_journal"])
    if replayable:
        print("\nReplayable safe actions:")
        for entry in replayable:
            suffix = ""
            if entry["action"] == "add_topic" and entry.get("created_topic_id") is not None:
                suffix = f" -> topic #{entry['created_topic_id']}"
            print(f"  [{entry['step']}] {entry['action']} — {entry.get('message', '')[:100]}{suffix}")
    else:
        print("\nReplayable safe actions: none")

    proposed_actions = payload.get("proposed_actions", [])
    if proposed_actions:
        print("\nApproval-gated follow-up actions:")
        for index, action in enumerate(proposed_actions, start=1):
            print(f"  [{index}] {action.get('action', '?')} — {action.get('message', '')[:100]}")
    else:
        print("\nApproval-gated follow-up actions: none")


def _write_preview_exports(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    output_dir = _resolve_output_dir(args.structure_dir)
    run_stamp = args.run_stamp or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    fmt = args.structure_format

    before_latest, before_stamped = _write_structure_snapshot(
        output_dir=output_dir,
        run_stamp=run_stamp,
        label="live_before",
        fmt=fmt,
        summary=payload["before_summary"],
        topic_map=payload["before_topic_map"],
    )
    after_latest, after_stamped = _write_structure_snapshot(
        output_dir=output_dir,
        run_stamp=run_stamp,
        label="preview_after",
        fmt=fmt,
        summary=payload["after_summary"],
        topic_map=payload["after_topic_map"],
    )

    print("\nStructure exports:")
    print(f"  live before : {before_latest}")
    print(f"  live before archive: {before_stamped}")
    print(f"  preview after: {after_latest}")
    print(f"  preview after archive: {after_stamped}")


def _write_live_after_export(args: argparse.Namespace) -> None:
    _ensure_project_imports()

    import db

    _init_databases_without_vector_bootstrap()
    live_after = db.get_topic_map()
    output_dir = _resolve_output_dir(args.structure_dir)
    run_stamp = args.run_stamp or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    latest_path, stamped_path = _write_structure_snapshot(
        output_dir=output_dir,
        run_stamp=run_stamp,
        label="live_after",
        fmt=args.structure_format,
        summary=_topic_map_summary(live_after),
        topic_map=live_after,
    )
    print(f"[apply] live after structure: {latest_path}")
    print(f"[apply] live after archive: {stamped_path}")


def _orchestrate(args: argparse.Namespace) -> int:
    print("Taxonomy shadow rebuild")
    print("Prerequisite: stop the bot and API before preview and apply.")

    with tempfile.TemporaryDirectory(prefix="taxonomy_shadow_rebuild_") as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        shadow_paths = _create_shadow_workspace(tmp_dir / "shadow")
        preview_file = tmp_dir / "preview.json"

        preview_env = os.environ.copy()
        preview_env["LEARN_DB_PATH"] = str(shadow_paths["knowledge_db"])
        preview_env["LEARN_CHAT_DB_PATH"] = str(shadow_paths["chat_db"])
        preview_env["LEARN_VECTOR_STORE_PATH"] = str(shadow_paths["vectors_dir"])

        preview_rc = _run_child(
            [
                "--phase",
                "preview-internal",
                "--result-file",
                str(preview_file),
                "--max-actions",
                str(args.max_actions),
                "--continuation-context-limit",
                str(args.continuation_context_limit),
            ],
            env=preview_env,
        )
        if preview_rc != 0:
            return preview_rc

        preview = _read_json(preview_file)
        _print_preview(preview)
        _write_preview_exports(args, preview)

        if preview.get("no_topics"):
            print("\nNo topics found. Nothing to rebuild.")
            return 0

        if not _replayable_entries(preview["action_journal"]) and not preview.get(
            "proposed_actions"
        ):
            print("\nNo taxonomy changes proposed.")
            return 0

        if not args.yes:
            answer = input("\nApply replayable safe actions to live data after backup? [y/N]: ")
            if answer.strip().lower() != "y":
                print("Aborted. No live changes made.")
                return 0

        apply_rc = _run_child(
            [
                "--phase",
                "apply-internal",
                "--preview-file",
                str(preview_file),
            ],
            env=os.environ.copy(),
        )
        if apply_rc == 0:
            _write_live_after_export(args)
        return apply_rc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=["orchestrate", "preview-internal", "apply-internal"],
        default="orchestrate",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--result-file", help=argparse.SUPPRESS)
    parser.add_argument("--preview-file", help=argparse.SUPPRESS)
    parser.add_argument("--yes", action="store_true", help="Apply without interactive confirmation")
    parser.add_argument("--run-stamp", help=argparse.SUPPRESS)
    parser.add_argument(
        "--conservative",
        dest="aggressive",
        action="store_false",
        help="Use the standard taxonomy prompt instead of the aggressive reconstruction directive",
    )
    parser.set_defaults(aggressive=True)
    parser.add_argument(
        "--max-actions",
        type=int,
        default=DEFAULT_MAX_ACTIONS,
        help="Maximum taxonomy actions to allow during preview",
    )
    parser.add_argument(
        "--continuation-context-limit",
        type=int,
        default=DEFAULT_CONTINUATION_CONTEXT_LIMIT,
        help="Characters of taxonomy context to retain in continuation prompts",
    )
    parser.add_argument(
        "--structure-format",
        choices=["md", "txt"],
        default=DEFAULT_STRUCTURE_FORMAT,
        help="Format for the exported topic-structure snapshots",
    )
    parser.add_argument(
        "--structure-dir",
        default=str(DEFAULT_STRUCTURE_DIR),
        help="Directory for exported topic-structure snapshots",
    )
    return parser


def main() -> int:
    _configure_stdio()
    parser = _build_parser()
    args = parser.parse_args()

    if args.phase == "preview-internal":
        if not args.result_file:
            parser.error("--result-file is required for preview-internal")
        return asyncio.run(_preview_internal(args))

    if args.phase == "apply-internal":
        if not args.preview_file:
            parser.error("--preview-file is required for apply-internal")
        return asyncio.run(_apply_internal(args))

    return _orchestrate(args)


if __name__ == "__main__":
    raise SystemExit(main())