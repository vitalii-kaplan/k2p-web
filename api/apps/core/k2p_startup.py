from __future__ import annotations

import json
import logging
import shlex
import subprocess
from pathlib import Path


class K2PStartupError(RuntimeError):
    pass


def _build_entrypoint_args(command: str | None) -> list[str]:
    if not command:
        return []
    entrypoint = shlex.split(command)
    if len(entrypoint) != 1:
        raise K2PStartupError("K2P_COMMAND must be a single executable (no args)")
    return ["--entrypoint", entrypoint[0]]


def _run_k2p_cli(
    *,
    docker_bin: str,
    image: str,
    command: str | None,
    cli_args: list[str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [docker_bin, "run", "--rm"] + _build_entrypoint_args(command) + [image] + cli_args,
        text=True,
        capture_output=True,
    )


def check_version_and_export_handlers(
    *,
    docker_bin: str,
    image: str,
    command: str | None,
    handlers_path: Path,
    logger: logging.Logger,
) -> None:
    logger.info(json.dumps({"event": "k2p_version_check_start", "image": image}))
    version_result = _run_k2p_cli(
        docker_bin=docker_bin,
        image=image,
        command=command,
        cli_args=["--version"],
    )
    if version_result.returncode != 0:
        raise K2PStartupError(
            "knime2py version check failed: "
            f"exit={version_result.returncode}, stderr_tail={(version_result.stderr or '')[-1000:]}"
        )
    logger.info(
        json.dumps(
            {
                "event": "k2p_version_check_ok",
                "image": image,
                "version": (version_result.stdout or "").strip(),
            }
        )
    )

    logger.info(json.dumps({"event": "k2p_handlers_export_start", "image": image}))
    handlers_result = _run_k2p_cli(
        docker_bin=docker_bin,
        image=image,
        command=command,
        cli_args=["--get-handlers"],
    )
    if handlers_result.returncode != 0:
        raise K2PStartupError(
            "knime2py handlers export failed: "
            f"exit={handlers_result.returncode}, stderr_tail={(handlers_result.stderr or '')[-1000:]}"
        )

    handlers_path.parent.mkdir(parents=True, exist_ok=True)
    handlers_path.write_text(handlers_result.stdout or "", encoding="utf-8")
    logger.info(
        json.dumps(
            {
                "event": "k2p_handlers_export_ok",
                "image": image,
                "path": str(handlers_path.resolve()),
            }
        )
    )
