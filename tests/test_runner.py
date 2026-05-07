from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from apps.jobs.runner import DockerRunner, safe_container_path_stem


class DockerRunnerTests(TestCase):
    def _runner(self, *, args_template: str | None = None) -> DockerRunner:
        root = Path(tempfile.gettempdir())
        return DockerRunner(
            docker_bin="docker",
            image="k2p:test",
            timeout_s=30,
            cpu="1",
            memory="512m",
            pids_limit="256",
            command=None,
            args_template=args_template,
            container_repo_root=root,
            container_job_storage_root=root,
            container_result_storage_root=root,
            host_repo_root="",
            host_job_storage_root="",
            host_result_storage_root="",
            logger=logging.getLogger("test"),
        )

    def test_safe_container_path_stem_sanitizes_upload_name(self) -> None:
        self.assertEqual(safe_container_path_stem("Sales Workflow.zip"), "Sales_Workflow")
        self.assertEqual(safe_container_path_stem("../.zip"), "workflow")

    def test_run_job_uses_workflow_name_for_container_input_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workflow_dir = Path(tmpdir) / "work"
            out_dir = Path(tmpdir) / "out"
            workflow_dir.mkdir()
            (workflow_dir / "workflow.knime").write_text("<root></root>", encoding="utf-8")

            completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            with patch("apps.jobs.runner.subprocess.run", return_value=completed) as run:
                self._runner().run_job("abc", workflow_dir, out_dir, workflow_name="discounts.zip")

        docker_run = run.call_args_list[1].args[0]
        self.assertIn(f"{workflow_dir}:/work/discounts:ro", docker_run)
        self.assertIn("/work/discounts", docker_run)

    def test_args_template_receives_workflow_name_input_path(self) -> None:
        runner = self._runner(args_template="convert --source {input} --dest {output}")
        self.assertEqual(
            runner._build_args(input_path="/work/discounts", out_dir="/work/out"),
            ["convert", "--source", "/work/discounts", "--dest", "/work/out"],
        )
