# Manual Taxonomy Rebuild — Operator Guide

## Overview

`scripts/taxonomy_shadow_rebuild.py` is the operator workflow for manually rebuilding the topic tree. It runs taxonomy mode against temporary shadow copies of the live databases and embedded vector store, records the replayable safe actions, and can then replay only those safe actions against live data after taking a fresh backup.

This is intentionally different from the weekly scheduler run:

- it is operator-triggered, not automatic
- it uses an aggressive reconstruction directive by default
- it writes before/after topic-tree snapshots for review
- it replays recorded safe actions instead of asking the LLM to improvise a fresh live run

## Prerequisites

1. Stop the bot and API before running the script.
2. Activate the virtual environment.
3. Run the script from the project root.
4. Make sure the configured LLM provider is reachable.
5. Leave enough disk space for a full backup and temporary shadow copies.

Why the offline requirement matters:

- SQLite and embedded Qdrant can be file-locked by other live processes.
- The apply phase verifies that live taxonomy still matches the preview baseline. Concurrent edits invalidate that safety check.

## How It Works

The script has three phases:

1. `orchestrate`
   Starts the workflow, creates a temp workspace, and launches preview/apply child processes.
2. `preview-internal`
   Runs taxonomy mode against temporary copies of `knowledge.db`, `chat_history.db`, and the vector store.
3. `apply-internal`
   Verifies the live baseline still matches preview, creates a backup, and replays the recorded safe actions.

The child-process design is deliberate. The repo uses environment-variable path overrides like `LEARN_DB_PATH`, `LEARN_CHAT_DB_PATH`, and `LEARN_VECTOR_STORE_PATH`, and those are read at import time. Separate processes keep preview and live apply isolated.

## Preview vs Apply

| Phase | Uses shadow data | Calls LLM | Takes backup | Writes live data |
|---|---|---|---|---|
| Preview | Yes | Yes | No | No |
| Apply | No | No | Yes | Yes, but only replayable safe actions |

Preview produces:

- replayable safe actions such as `add_topic` and `link_topics`
- approval-gated follow-up actions such as `update_topic` or `unlink_topics`
- structure snapshots showing `live_before` and `preview_after`

Apply does:

1. verify the live topic map matches the preview baseline
2. create a fresh backup
3. replay only the safe actions in the recorded order
4. verify the live topic map now matches the preview-after structure
5. write a `live_after` snapshot

If the live taxonomy changes between preview and apply, apply aborts.

## Aggressive vs Conservative Mode

By default the script adds an operator directive that makes taxonomy mode more aggressive than the normal weekly run. It tells the model to prefer meaningful restructures over preserving the status quo and to use more of the action budget on real grouping/reparenting work.

Use `--conservative` to disable that directive and fall back to the standard taxonomy prompt.

The aggressive mode still respects the hard taxonomy constraints:

- no score changes
- no suppressed rename re-proposals
- no non-empty topic deletions
- approval-gated actions remain approval-gated

## Backup Behavior

The backup is taken during apply, immediately before the first live write.

Default location:

- `backups/` in the project root

Override with:

- `LEARN_BACKUP_DIR`

Each backup directory contains:

```text
backups/
  2026-04-07_20-02-07_661517/
    knowledge.db
    chat_history.db
    vectors/
```

On Windows, OneDrive or Defender can briefly lock freshly copied files in the vector-store backup. The backup service retries the final temp-dir rename several times before failing.

## Structure Export Files

By default the script writes structure snapshots to:

- `backups/taxonomy_shadow_rebuild/`

Files written per run:

- `live_before_latest.md`
- `preview_after_latest.md`
- `live_after_latest.md` after a successful apply
- timestamped archive copies for each of the above

Use:

- `--structure-format txt` for plain-text output
- `--structure-dir PATH` to write the snapshots elsewhere

## Approval-Gated Limitations

The script only replays safe actions.

Replayable safe actions:

- `add_topic`
- `link_topics`

Read-only actions like `fetch` and `list_topics` can appear in the journal but are not replayed.

Approval-gated actions are never auto-applied by this script:

- `update_topic`
- `unlink_topics`
- `delete_topic`
- `unlink_concept`
- `update_concept`

Those are printed as manual follow-up work only.

## Common Windows & OneDrive Issues

### Backup rename fails with `PermissionError`

This is usually a transient file-lock issue, not an admin-rights issue.

Common causes:

- OneDrive sync grabbing newly copied backup files
- Defender or another file indexer touching the copied vector-store files

Recommended fixes:

1. Pause OneDrive sync and rerun.
2. Set `LEARN_BACKUP_DIR` to a folder outside OneDrive.
3. Set `--structure-dir` to a folder outside OneDrive if export writes also get noisy.

### MPNet / Hugging Face load messages appear

That is expected when preview or apply actually needs to create topics, because vector upserts require embeddings.

### Live apply aborts because taxonomy changed

That means the live topic map no longer matches the preview baseline. Rerun the script from preview.

## Example Commands

Default aggressive run with confirmation:

```bash
python scripts/taxonomy_shadow_rebuild.py
```

Aggressive run, skip confirmation prompt:

```bash
python scripts/taxonomy_shadow_rebuild.py --yes
```

Conservative run:

```bash
python scripts/taxonomy_shadow_rebuild.py --conservative
```

Raise the preview budget:

```bash
python scripts/taxonomy_shadow_rebuild.py --max-actions 120
```

Export plain text instead of markdown:

```bash
python scripts/taxonomy_shadow_rebuild.py --structure-format txt
```

Write snapshots outside OneDrive:

```bash
python scripts/taxonomy_shadow_rebuild.py --structure-dir C:\tmp\taxonomy_exports
```

PowerShell example with backup directory outside OneDrive:

```powershell
$env:LEARN_BACKUP_DIR = "$env:LOCALAPPDATA\learning_agent_backups"
& .\venv\Scripts\python.exe .\scripts\taxonomy_shadow_rebuild.py
```

## Exit Conditions

Typical apply outcomes:

- success: backup completed, safe actions replayed, `live_after` snapshot written
- baseline mismatch: live taxonomy changed after preview, so apply aborts
- backup failure: no live actions replayed
- replay mismatch: live replay finished but final structure does not match the preview-after structure

## Manual Rollback

If you want to undo a successful apply:

1. stop the bot and API
2. restore `knowledge.db`, `chat_history.db`, and `vectors/` from the backup directory created by the apply phase
3. restart the application

The script does not have an automated restore command.

## Cross References

- `scripts/taxonomy_shadow_rebuild.py`
- `data/skills/taxonomy.md`
- `services/pipeline.py`
- `services/backup.py`
- `docs/DEVNOTES.md`