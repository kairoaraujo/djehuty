"""Unit tests for parsing the usage-statistics block (djehuty.web.ui).

Covers both config formats (JSON and XML), enabled and disabled states,
the database value via a literal and via ${env:...} / ${file:...} secret
references (JSON only, matching the parser), default and overridden flush
settings, and malformed values.
"""

import logging

import pytest
from defusedxml import ElementTree

from djehuty.web.config import config
from djehuty.web.config.json_parser import JsonConfigElement
from djehuty.web.ui import read_usage_statistics_configuration

logger = logging.getLogger("test_usage_statistics_config")


@pytest.fixture(autouse=True)
def reset_config():
    saved = (
        config.usage_statistics_enabled,
        config.usage_statistics_database_url,
        config.usage_statistics_flush_interval,
        config.usage_statistics_flush_batch_size,
    )
    config.usage_statistics_enabled = False
    config.usage_statistics_database_url = None
    config.usage_statistics_flush_interval = 5
    config.usage_statistics_flush_batch_size = 1000
    yield
    (
        config.usage_statistics_enabled,
        config.usage_statistics_database_url,
        config.usage_statistics_flush_interval,
        config.usage_statistics_flush_batch_size,
    ) = saved


def _json(data):
    return JsonConfigElement("djehuty", data)


def _xml(inner):
    return ElementTree.fromstring(f"<djehuty>{inner}</djehuty>")


def test_absent_block_leaves_defaults():
    read_usage_statistics_configuration(_json({}), logger)
    assert config.usage_statistics_enabled is False
    assert config.usage_statistics_database_url is None
    assert config.usage_statistics_flush_interval == 5
    assert config.usage_statistics_flush_batch_size == 1000


@pytest.mark.parametrize(
    "root",
    [
        _json(
            {
                "usage-statistics": {
                    "enabled": 1,
                    "database": "postgresql+psycopg://u:p@host:5432/stats",
                    "flush-interval": 10,
                    "flush-batch-size": 500,
                }
            }
        ),
        _xml(
            '<usage-statistics enabled="1">'
            "<database>postgresql+psycopg://u:p@host:5432/stats</database>"
            "<flush-interval>10</flush-interval>"
            "<flush-batch-size>500</flush-batch-size>"
            "</usage-statistics>"
        ),
    ],
)
def test_enabled_block_is_parsed(root):
    read_usage_statistics_configuration(root, logger)
    assert config.usage_statistics_enabled is True
    assert config.usage_statistics_database_url == "postgresql+psycopg://u:p@host:5432/stats"
    assert config.usage_statistics_flush_interval == 10
    assert config.usage_statistics_flush_batch_size == 500


@pytest.mark.parametrize(
    "root",
    [
        _json({"usage-statistics": {"enabled": 0, "database": "sqlite:///stats.db"}}),
        _xml(
            '<usage-statistics enabled="0"><database>sqlite:///stats.db</database></usage-statistics>'
        ),
    ],
)
def test_disabled_block_still_reads_database(root):
    read_usage_statistics_configuration(root, logger)
    assert config.usage_statistics_enabled is False
    assert config.usage_statistics_database_url == "sqlite:///stats.db"


def test_missing_enabled_attribute_defaults_to_disabled():
    root = _xml("<usage-statistics><database>sqlite:///stats.db</database></usage-statistics>")
    read_usage_statistics_configuration(root, logger)
    assert config.usage_statistics_enabled is False
    assert config.usage_statistics_database_url == "sqlite:///stats.db"


def test_defaults_kept_when_flush_settings_absent():
    root = _json({"usage-statistics": {"enabled": 1, "database": "sqlite://"}})
    read_usage_statistics_configuration(root, logger)
    assert config.usage_statistics_flush_interval == 5
    assert config.usage_statistics_flush_batch_size == 1000


def test_database_env_reference_is_resolved(monkeypatch):
    monkeypatch.setenv("DJEHUTY_TEST_STATS_URL", "postgresql+psycopg://env@host/stats")
    root = _json({"usage-statistics": {"enabled": 1, "database": "${env:DJEHUTY_TEST_STATS_URL}"}})
    read_usage_statistics_configuration(root, logger)
    assert config.usage_statistics_database_url == "postgresql+psycopg://env@host/stats"


def test_database_file_reference_is_resolved(tmp_path):
    secret = tmp_path / "stats-url"
    secret.write_text("postgresql+psycopg://file@host/stats\n", encoding="utf-8")
    root = _json({"usage-statistics": {"enabled": 1, "database": f"${{file:{secret}}}"}})
    read_usage_statistics_configuration(root, logger)
    assert config.usage_statistics_database_url == "postgresql+psycopg://file@host/stats"


def test_malformed_enabled_warns_and_disables(caplog):
    root = _xml('<usage-statistics enabled="yes"><database>sqlite://</database></usage-statistics>')
    with caplog.at_level(logging.ERROR):
        read_usage_statistics_configuration(root, logger)
    assert config.usage_statistics_enabled is False
    assert "usage-statistics/enabled" in caplog.text


def test_malformed_flush_values_keep_defaults(caplog):
    root = _xml(
        '<usage-statistics enabled="1">'
        "<database>sqlite://</database>"
        "<flush-interval>soon</flush-interval>"
        "<flush-batch-size>lots</flush-batch-size>"
        "</usage-statistics>"
    )
    with caplog.at_level(logging.ERROR):
        read_usage_statistics_configuration(root, logger)
    assert config.usage_statistics_flush_interval == 5
    assert config.usage_statistics_flush_batch_size == 1000
    assert "usage-statistics/flush-interval" in caplog.text
    assert "usage-statistics/flush-batch-size" in caplog.text
