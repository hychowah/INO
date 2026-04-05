"""
Kimi-CLI subprocess wrapper for the learning agent bot.
"""

import asyncio
import logging
import os
import subprocess

import config

logger = logging.getLogger("kimi")


async def run_kimi(
    command: str, *, stdin_text: str = None, timeout: int = None
) -> subprocess.CompletedProcess:
    """
    Run a kimi-cli command asynchronously (non-blocking via thread pool).

    Args:
        command: kimi flags/args (excluding executable path).
        stdin_text: Optional text to pipe via stdin.
        timeout: Override timeout in seconds.

    Returns:
        subprocess.CompletedProcess with stdout/stderr.
    """
    kimi_path = config.KIMI_CLI_PATH
    if " " in kimi_path and not (kimi_path.startswith('"') or kimi_path.startswith("'")):
        kimi_path = f'"{kimi_path}"'

    full_command = f"{kimi_path} {command}".strip()
    timeout = timeout or config.COMMAND_TIMEOUT

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    kwargs = dict(
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(config.BASE_DIR.parent),  # PA root
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if stdin_text is not None:
        kwargs["input"] = stdin_text

    preview = command[:100].replace("\n", " ")
    logger.info(f"Running kimi: {preview!r} (timeout={timeout}s)")
    result = await asyncio.to_thread(subprocess.run, full_command, **kwargs)
    logger.debug(
        f"Kimi exit={result.returncode}, "
        f"stdout={len(result.stdout)} chars, stderr={len(result.stderr)} chars"
    )
    if result.returncode != 0:
        filtered = _filter_stderr(result.stderr)
        if filtered:
            logger.warning(f"Kimi stderr: {filtered[:300]}")
    return result


def _filter_stderr(stderr: str) -> str:
    """Filter out kimi's decorative box-drawing output from stderr."""
    if not stderr:
        return ""
    filtered = [
        line
        for line in stderr.strip().split("\n")
        if line.strip()
        and not line.startswith("┌")
        and not line.startswith("│")
        and not line.startswith("└")
        and "✓" not in line
        and "✗" not in line
    ]
    return "\n".join(filtered)
