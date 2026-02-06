from __future__ import annotations

import json
import logging
import shlex
import subprocess
from pathlib import Path
from typing import Any


class RunnerError(Exception):
    def __init__(
        self,
        message: str,
        *,
        exit_code: int | None = None,
        stdout_tail: str = "",
        stderr_tail: str = "",
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stdout_tail = stdout_tail
        self.stderr_tail = stderr_tail


def _tail_file(path: Path, *, max_lines: int = 40, max_bytes: int = 4000) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    text = data.decode(errors="replace")
    lines = text.splitlines()[-max_lines:]
    return "\n".join(lines).strip()


def build_k2p_args(input_zip: str = "/work/input.zip", out_dir: str = "/work/out") -> list[str]:
    return ["--in-zip", input_zip, "--out", out_dir]


class DockerRunner:
    def __init__(
        self,
        *,
        docker_bin: str,
        image: str,
        timeout_s: int,
        cpu: str,
        memory: str,
        pids_limit: str,
        command: str | None,
        args_template: str | None,
        container_repo_root: Path,
        container_job_storage_root: Path,
        container_result_storage_root: Path,
        host_repo_root: str,
        host_job_storage_root: str,
        host_result_storage_root: str,
        logger: logging.Logger,
    ) -> None:
        self.image = image
        self.docker_bin = docker_bin
        self.timeout_s = timeout_s
        self.cpu = cpu
        self.memory = memory
        self.pids_limit = pids_limit
        self.command = command or ""
        self.args_template = args_template or ""
        self.logger = logger
        self.container_repo_root = container_repo_root
        self.container_job_storage_root = container_job_storage_root
        self.container_result_storage_root = container_result_storage_root
        self.host_repo_root = host_repo_root
        self.host_job_storage_root = host_job_storage_root
        self.host_result_storage_root = host_result_storage_root

    def _ensure_image(self) -> None:
        inspect = subprocess.run(
            [self.docker_bin, "image", "inspect", self.image],
            text=True,
            capture_output=True,
        )
        if inspect.returncode == 0:
            return
        pull = subprocess.run(
            [self.docker_bin, "pull", self.image],
            text=True,
            capture_output=True,
        )
        if pull.returncode != 0:
            raise RunnerError(
                "image_pull_failed",
                exit_code=pull.returncode,
                stdout_tail=(pull.stdout or "")[-1000:],
                stderr_tail=(pull.stderr or "")[-1000:],
            )

    def _resolve_host_path(self, path: Path) -> Path:
        if self.host_job_storage_root:
            try:
                rel = path.relative_to(self.container_job_storage_root)
                return Path(self.host_job_storage_root) / rel
            except ValueError:
                pass
        if self.host_result_storage_root:
            try:
                rel = path.relative_to(self.container_result_storage_root)
                return Path(self.host_result_storage_root) / rel
            except ValueError:
                pass
        if self.host_repo_root:
            try:
                rel = path.relative_to(self.container_repo_root)
                return Path(self.host_repo_root) / rel
            except ValueError:
                pass
        return path

    def _build_command(self) -> list[str]:
        if self.command:
            return shlex.split(self.command)
        return ["k2p"]

    def _build_args(self) -> list[str]:
        if self.args_template:
            rendered = self.args_template.format(input="/work/input.zip", output="/work/out")
            return shlex.split(rendered)
        return build_k2p_args()

    def run_job(self, job_id: str, workflow_zip_path: Path, out_dir: Path) -> dict[str, Any]:
        name = f"k2pweb-job-{job_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_dir.chmod(0o777)

        stdout_path = out_dir / "stdout.log"
        stderr_path = out_dir / "stderr.log"

        host_in = self._resolve_host_path(workflow_zip_path)
        host_out = self._resolve_host_path(out_dir)
        host_out.mkdir(parents=True, exist_ok=True)

        self._ensure_image()

        entrypoint = self._build_command()
        entrypoint_arg: list[str] = []
        if entrypoint:
            # Override image ENTRYPOINT to avoid any baked-in positional workflow path.
            if len(entrypoint) != 1:
                raise RunnerError("K2P_COMMAND must be a single executable (no args)")
            entrypoint_arg = ["--entrypoint", entrypoint[0]]

        base_cmd = [
            self.docker_bin,
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--cpus",
            self.cpu,
            "--memory",
            self.memory,
            "--pids-limit",
            self.pids_limit,
            "--user",
            "65534:65534",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "-v",
            f"{host_in}:/work/input.zip:ro",
            "-v",
            f"{host_out}:/work/out:rw",
            "-w",
            "/work",
        ] + entrypoint_arg + [self.image]

        self.logger.info(json.dumps({"event": "runner_start", "job_id": job_id, "image": self.image}))

        def run_once(args: list[str], *, append: bool = False) -> subprocess.CompletedProcess:
            mode = "a" if append else "w"
            with stdout_path.open(mode) as stdout_f, stderr_path.open(mode) as stderr_f:
                return subprocess.run(
                    base_cmd + args,
                    text=True,
                    stdout=stdout_f,
                    stderr=stderr_f,
                    timeout=self.timeout_s,
                )

        try:
            args = self._build_args()
            p = run_once(args, append=False)
        except subprocess.TimeoutExpired:
            subprocess.run([self.docker_bin, "rm", "-f", name], check=False, capture_output=True, text=True)
            stdout_tail = _tail_file(stdout_path)
            stderr_tail = _tail_file(stderr_path)
            raise RunnerError(
                f"timeout after {self.timeout_s}s",
                exit_code=None,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
            )

        stdout_tail = _tail_file(stdout_path)
        stderr_tail = _tail_file(stderr_path)
        if p.returncode != 0:
            raise RunnerError(
                "non-zero exit",
                exit_code=p.returncode,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
            )

        artifacts = [str(p.relative_to(out_dir)) for p in out_dir.rglob("*") if p.is_file()]
        return {
            "exit_code": p.returncode,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "artifacts": artifacts,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
