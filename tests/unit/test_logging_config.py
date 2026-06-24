"""Tests for web/backend/veritas_web/logging_config.py."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from unittest import mock

import pytest

from web.backend.veritas_web import logging_config


@pytest.fixture(autouse=True)
def _reset_logging_config():
    """Reset the module-level _CONFIGURED flag and clean up veritas logger handlers."""
    logging_config._CONFIGURED = False
    root = logging.getLogger("veritas")
    root.handlers.clear()
    root.setLevel(logging.WARNING)  # restore default
    yield
    logging_config._CONFIGURED = False
    root.handlers.clear()


def test_configure_logging_adds_stream_handler():
    logging_config.configure_logging()

    root = logging.getLogger("veritas")
    stream_handlers = [
        h
        for h in root.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, (RotatingFileHandler, logging.FileHandler))
    ]
    assert len(stream_handlers) >= 1
    assert root.level == logging.INFO


def test_configure_logging_reads_env_level(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VERITAS_LOG_LEVEL", "DEBUG")
    logging_config.configure_logging()

    root = logging.getLogger("veritas")
    assert root.level == logging.DEBUG


def test_configure_logging_explicit_level_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("VERITAS_LOG_LEVEL", "WARNING")
    logging_config.configure_logging(level="ERROR")

    root = logging.getLogger("veritas")
    assert root.level == logging.ERROR


def test_configure_logging_idempotent():
    logging_config.configure_logging()
    handler_count = len(logging.getLogger("veritas").handlers)
    logging_config.configure_logging()  # second call
    assert len(logging.getLogger("veritas").handlers) == handler_count


def test_rotating_file_handler_created(tmp_path):
    log_dir = str(tmp_path / "logs")
    with mock.patch.dict(os.environ, {"VERITAS_LOG_DIR": log_dir}):
        logging_config.configure_logging()

    root = logging.getLogger("veritas")
    file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 1
    assert file_handlers[0].maxBytes == 10 * 1024 * 1024
    assert file_handlers[0].backupCount == 5
    assert os.path.isfile(os.path.join(log_dir, "veritas.log"))


def test_rotating_file_handler_writes(tmp_path):
    log_dir = str(tmp_path / "logs")
    with mock.patch.dict(os.environ, {"VERITAS_LOG_DIR": log_dir}):
        logging_config.configure_logging()

    root = logging.getLogger("veritas")
    root.info("test message from logging_config test")

    log_file = os.path.join(log_dir, "veritas.log")
    content = open(log_file, encoding="utf-8").read()
    assert "test message from logging_config test" in content


def test_log_format():
    logging_config.configure_logging()
    root = logging.getLogger("veritas")
    for handler in root.handlers:
        fmt = handler.formatter
        assert fmt is not None
        assert "%(asctime)s" in fmt._fmt
        assert "%(levelname)s" in fmt._fmt
        assert "%(name)s" in fmt._fmt


def test_fallback_on_unwritable_log_dir():
    """When log dir cannot be created, we degrade to stderr only."""
    with mock.patch.dict(
        os.environ, {"VERITAS_LOG_DIR": "/proc/nonexistent/impossible"}
    ):
        logging_config.configure_logging()

    root = logging.getLogger("veritas")
    file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    # No file handler should have been added
    assert len(file_handlers) == 0
    # But stream handler should still be present
    stream_handlers = [
        h
        for h in root.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, (RotatingFileHandler, logging.FileHandler))
    ]
    assert len(stream_handlers) >= 1
