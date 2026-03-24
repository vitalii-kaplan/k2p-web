from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.core.apps import CoreConfig
from apps.core.k2p_startup import K2PStartupError, check_version_and_export_handlers


class K2PStartupTests(SimpleTestCase):
    def test_check_version_and_export_handlers_writes_static_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            handlers_path = Path(tmpdir) / "static" / "meta" / "handlers.csv"
            results = [
                CompletedProcess(args=["docker"], returncode=0, stdout="0.1.16\n", stderr=""),
                CompletedProcess(
                    args=["docker"],
                    returncode=0,
                    stdout='{"handlers":[{"id":"x"}]}\n',
                    stderr="",
                ),
            ]

            with patch("apps.core.k2p_startup.subprocess.run", side_effect=results) as run:
                with patch("apps.core.k2p_startup.logging.Logger.info") as logger_info:
                    check_version_and_export_handlers(
                        docker_bin="docker",
                        image="example/knime2py:0.1.16",
                        command=None,
                        handlers_path=handlers_path,
                        logger=logging.getLogger("k2p.api"),
                    )

            self.assertEqual(handlers_path.read_text(encoding="utf-8"), '{"handlers":[{"id":"x"}]}\n')
            self.assertEqual(run.call_count, 2)
            events = [json.loads(call.args[0])["event"] for call in logger_info.call_args_list]
            self.assertEqual(
                events,
                [
                    "k2p_version_check_start",
                    "k2p_version_check_ok",
                    "k2p_handlers_export_start",
                    "k2p_handlers_export_ok",
                ],
            )

    def test_check_version_and_export_handlers_raises_on_version_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            handlers_path = Path(tmpdir) / "static" / "meta" / "handlers.csv"
            result = CompletedProcess(args=["docker"], returncode=7, stdout="", stderr="boom")

            with patch("apps.core.k2p_startup.subprocess.run", return_value=result):
                with self.assertRaisesRegex(K2PStartupError, "version check failed"):
                    check_version_and_export_handlers(
                        docker_bin="docker",
                        image="example/knime2py:0.1.16",
                        command=None,
                        handlers_path=handlers_path,
                        logger=logging.getLogger("k2p.api"),
                    )

            self.assertFalse(handlers_path.exists())


class CoreConfigReadyTests(SimpleTestCase):
    @override_settings(
        DEBUG=False,
        DOCKER_BIN="docker",
        K2P_IMAGE="example/knime2py:0.1.16",
        K2P_COMMAND="",
        K2P_HANDLERS_STATIC_FILE="/tmp/handlers.csv",
    )
    def test_ready_runs_api_startup_checks(self) -> None:
        config = CoreConfig("apps.core", importlib.import_module("apps.core"))
        original_argv = sys.argv[:]
        try:
            sys.argv = ["gunicorn", "k2pweb.wsgi:application"]
            with patch("apps.core.apps.log_db_settings") as log_db_settings:
                with patch("apps.core.apps.check_version_and_export_handlers") as startup_check:
                    config.ready()
        finally:
            sys.argv = original_argv

        log_db_settings.assert_called_once()
        startup_check.assert_called_once()

    @override_settings(
        DEBUG=True,
        DOCKER_BIN="docker",
        K2P_IMAGE="example/knime2py:0.1.16",
        K2P_COMMAND="",
        K2P_HANDLERS_STATIC_FILE="/tmp/handlers.csv",
    )
    def test_ready_skips_before_reloader_main_process(self) -> None:
        config = CoreConfig("apps.core", importlib.import_module("apps.core"))
        previous_run_main = os.environ.pop("RUN_MAIN", None)
        try:
            with patch("apps.core.apps.check_version_and_export_handlers") as startup_check:
                config.ready()
        finally:
            if previous_run_main is not None:
                os.environ["RUN_MAIN"] = previous_run_main

        startup_check.assert_not_called()

    @override_settings(
        DEBUG=False,
        DOCKER_BIN="docker",
        K2P_IMAGE="example/knime2py:0.1.16",
        K2P_COMMAND="",
        K2P_HANDLERS_STATIC_FILE="/tmp/handlers.csv",
    )
    def test_ready_skips_django_test_command(self) -> None:
        config = CoreConfig("apps.core", importlib.import_module("apps.core"))
        original_argv = sys.argv[:]
        try:
            sys.argv = ["manage.py", "test"]
            with patch("apps.core.apps.check_version_and_export_handlers") as startup_check:
                config.ready()
        finally:
            sys.argv = original_argv

        startup_check.assert_not_called()
