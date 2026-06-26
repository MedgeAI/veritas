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
    """Reset the module-level _CONFIGURED flag and clean up root logger handlers."""
    logging_config._CONFIGURED = False
    # Save and restore root logger state.
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    root.handlers.clear()
    root.setLevel(logging.WARNING)
    # Clear VERITAS_DEV to get deterministic defaults.
    env_patch = mock.patch.dict(os.environ, {"VERITAS_DEV": ""}, clear=False)
    env_patch.start()
    yield
    env_patch.stop()
    logging_config._CONFIGURED = False
    root.handlers.clear()
    root.handlers.extend(saved_handlers)
    root.setLevel(saved_level)


def test_configure_logging_adds_stream_handler(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("VERITAS_DEV", raising=False)
    monkeypatch.delenv("VERITAS_LOG_LEVEL", raising=False)
    logging_config.configure_logging()

    root = logging.getLogger()
    stream_handlers = [
        h
        for h in root.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, (RotatingFileHandler, logging.FileHandler))
    ]
    assert len(stream_handlers) >= 1
    assert root.level == logging.INFO  # VERITAS_DEV="" → INFO


def test_configure_logging_reads_env_level(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VERITAS_LOG_LEVEL", "DEBUG")
    logging_config.configure_logging()

    root = logging.getLogger()
    assert root.level == logging.DEBUG


def test_configure_logging_explicit_level_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("VERITAS_LOG_LEVEL", "WARNING")
    logging_config.configure_logging(level="ERROR")

    root = logging.getLogger()
    assert root.level == logging.ERROR


def test_configure_logging_idempotent():
    logging_config.configure_logging()
    handler_count = len(logging.getLogger().handlers)
    logging_config.configure_logging()  # second call
    assert len(logging.getLogger().handlers) == handler_count


def test_rotating_file_handler_created(tmp_path):
    log_dir = str(tmp_path / "logs")
    with mock.patch.dict(os.environ, {"VERITAS_LOG_DIR": log_dir}):
        logging_config.configure_logging()

    root = logging.getLogger()
    file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 1
    assert file_handlers[0].maxBytes == 10 * 1024 * 1024
    assert file_handlers[0].backupCount == 5
    assert os.path.isfile(os.path.join(log_dir, "veritas.log"))


def test_rotating_file_handler_writes(tmp_path):
    log_dir = str(tmp_path / "logs")
    with mock.patch.dict(os.environ, {"VERITAS_LOG_DIR": log_dir}):
        logging_config.configure_logging()

    root = logging.getLogger()
    root.info("test message from logging_config test")

    log_file = os.path.join(log_dir, "veritas.log")
    content = open(log_file, encoding="utf-8").read()
    assert "test message from logging_config test" in content


def test_log_format():
    logging_config.configure_logging()
    root = logging.getLogger()
    # Filter to only plain StreamHandlers (not pytest's CapturingLogHandler
    # or RotatingFileHandler) — these are the ones we added.
    our_handlers = [
        h
        for h in root.handlers
        if type(h) is logging.StreamHandler  # exact type, not subclass
    ]
    assert len(our_handlers) >= 1
    for handler in our_handlers:
        fmt = handler.formatter
        assert fmt is not None
        assert "%(asctime)s" in fmt._fmt
        assert "%(levelname)" in fmt._fmt
        assert "%(name)s" in fmt._fmt


def test_fallback_on_unwritable_log_dir():
    """When log dir cannot be created, we degrade to stderr only."""
    with mock.patch.dict(
        os.environ, {"VERITAS_LOG_DIR": "/proc/nonexistent/impossible"}
    ):
        logging_config.configure_logging()

    root = logging.getLogger()
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


def test_dev_mode_defaults_to_debug(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VERITAS_DEV", "1")
    monkeypatch.delenv("VERITAS_LOG_LEVEL", raising=False)
    logging_config.configure_logging()

    root = logging.getLogger()
    assert root.level == logging.DEBUG
