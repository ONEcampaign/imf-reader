"""Tests that imf_reader leaves logging configuration to the application."""

import logging
import subprocess
import sys

import pytest

import imf_reader.config
from imf_reader.weo import api

# Run in a fresh interpreter so no other test's logging setup leaks in.
_IMPORT_CHECK = """
import logging

import imf_reader
import imf_reader.cache
import imf_reader.cache.dataframe
import imf_reader.config
import imf_reader.sdr
import imf_reader.sdr.read_announcements
import imf_reader.sdr.read_exchange_rate
import imf_reader.sdr.read_interest_rate
import imf_reader.weo
import imf_reader.weo.api
import imf_reader.weo.parser
import imf_reader.weo.reader
import imf_reader.weo.scraper

loggers = {
    name: logger
    for name, logger in logging.root.manager.loggerDict.items()
    if name.split(".")[0] == "imf_reader" and isinstance(logger, logging.Logger)
}
assert loggers
for name, logger in loggers.items():
    assert logger.handlers == [], name
    assert logger.level == logging.NOTSET, name
    assert logger.propagate, name
"""

# dictConfig closes every existing handler, including pytest's, so it runs apart.
_DICT_CONFIG_CHECK = """
import logging
import logging.config

import imf_reader.weo.api

logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "loggers": {"imf_reader": {"level": "INFO"}},
    }
)
records = []
handler = logging.Handler()
handler.emit = records.append
logging.getLogger().addHandler(handler)

imf_reader.weo.api.logger.info("progress")

assert logging.getLogger("imf_reader").level == logging.INFO
assert [record.getMessage() for record in records] == ["progress"]
"""


def _run_in_fresh_interpreter(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # runs this file's own fixed scripts
        [sys.executable, "-W", "error::DeprecationWarning", "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )


def test_import_leaves_logging_configuration_to_the_application():
    """Importing imf_reader sets no handlers or levels, and its loggers propagate."""
    result = _run_in_fresh_interpreter(_IMPORT_CHECK)

    assert result.returncode == 0, result.stderr


def test_dict_config_of_the_package_logger_reaches_module_records():
    """Configuring ``imf_reader`` with dictConfig governs records from its modules."""
    result = _run_in_fresh_interpreter(_DICT_CONFIG_CHECK)

    assert result.returncode == 0, result.stderr


def test_module_records_reach_the_root_logger():
    """A record from a module logger reaches a handler on the root logger."""
    # caplog also attaches to non-propagating loggers, so it cannot show propagation.
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    try:
        api.logger.warning("progress")
    finally:
        root_logger.removeHandler(handler)

    assert [record.getMessage() for record in records] == ["progress"]


def test_config_logger_is_deprecated():
    """``imf_reader.config.logger`` warns and returns the ``imf_reader.config`` logger."""
    with pytest.warns(DeprecationWarning, match=r"imf_reader\.config\.logger"):
        from imf_reader.config import logger

    assert logger is logging.getLogger("imf_reader.config")


def test_config_logger_sits_under_the_package_logger():
    """``imf_reader.config`` is a child of ``imf_reader`` and propagates to it."""
    package_logger = logging.getLogger("imf_reader")
    config_logger = logging.getLogger("imf_reader.config")

    assert config_logger.parent is package_logger
    assert config_logger.propagate


def test_level_on_the_old_logger_name_governs_module_records(caplog):
    """A level set on ``imf_reader.config`` by name filters WEO and SDR records."""
    config_logger = logging.getLogger("imf_reader.config")
    config_logger.setLevel(logging.WARNING)
    try:
        with caplog.at_level(logging.INFO):
            api.logger.info("hidden")
            api.logger.warning("shown")
    finally:
        config_logger.setLevel(logging.NOTSET)

    assert [record.getMessage() for record in caplog.records] == ["shown"]


def test_unknown_config_attribute_raises():
    """Only ``logger`` is served lazily. Other missing names raise AttributeError."""
    with pytest.raises(AttributeError, match="has no attribute 'missing'"):
        imf_reader.config.missing  # noqa: B018  # the lookup itself is under test
