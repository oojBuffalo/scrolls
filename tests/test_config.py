"""Tests for config.toml reading (IDEAS.md §8's [classify] section, ADR 0016)."""

import pytest

from scrolls.classify_llm import DEFAULT_MODEL
from scrolls.config import ConfigError, ScrollsConfig, load_config, resolve_llm_model


def write_config(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_file_yields_defaults(tmp_path):
    config = load_config(tmp_path / "config.toml")
    assert config == ScrollsConfig(default_engine="rules", llm_model=None)


def test_empty_file_yields_defaults(tmp_path):
    config = load_config(write_config(tmp_path, ""))
    assert config == ScrollsConfig(default_engine="rules", llm_model=None)


def test_comment_only_template_yields_defaults(tmp_path):
    from scrolls.pipeline import CONFIG_TEMPLATE

    config = load_config(write_config(tmp_path, CONFIG_TEMPLATE))
    assert config == ScrollsConfig(default_engine="rules", llm_model=None)


def test_classify_section_is_read(tmp_path):
    config = load_config(
        write_config(
            tmp_path,
            '[classify]\ndefault_engine = "llm"\nllm_model = "claude-haiku-4-5"\n',
        )
    )
    assert config.default_engine == "llm"
    assert config.llm_model == "claude-haiku-4-5"


def test_malformed_toml_is_a_config_error(tmp_path):
    path = write_config(tmp_path, "[classify\ndefault_engine =")
    with pytest.raises(ConfigError) as excinfo:
        load_config(path)
    assert "config.toml" in str(excinfo.value)


def test_unknown_engine_is_a_config_error(tmp_path):
    path = write_config(tmp_path, '[classify]\ndefault_engine = "vibes"\n')
    with pytest.raises(ConfigError) as excinfo:
        load_config(path)
    assert "vibes" in str(excinfo.value)


def test_non_string_llm_model_is_a_config_error(tmp_path):
    path = write_config(tmp_path, "[classify]\nllm_model = 42\n")
    with pytest.raises(ConfigError):
        load_config(path)


def test_resolve_llm_model_prefers_env_then_config_then_default(monkeypatch):
    monkeypatch.delenv("SCROLLS_LLM_MODEL", raising=False)
    assert resolve_llm_model(ScrollsConfig()) == DEFAULT_MODEL
    assert (
        resolve_llm_model(ScrollsConfig(llm_model="claude-haiku-4-5"))
        == "claude-haiku-4-5"
    )
    monkeypatch.setenv("SCROLLS_LLM_MODEL", "claude-sonnet-4-6")
    assert (
        resolve_llm_model(ScrollsConfig(llm_model="claude-haiku-4-5"))
        == "claude-sonnet-4-6"
    )
