from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_server.multi_agent.core.config import LakebaseConfig


class _ModelConfigStub:
    def __init__(self, values):
        self._values = values

    def get(self, key):
        return self._values.get(key)


def test_lakebase_config_prefers_autoscaling_env(monkeypatch):
    monkeypatch.setenv("LAKEBASE_AUTOSCALING_PROJECT", "project-dev")
    monkeypatch.setenv("LAKEBASE_AUTOSCALING_BRANCH", "production")
    monkeypatch.delenv("LAKEBASE_INSTANCE_NAME", raising=False)

    config = LakebaseConfig.from_env()

    assert config.is_autoscaling() is True
    assert config.runtime_kwargs() == {
        "project": "project-dev",
        "branch": "production",
    }


def test_lakebase_config_falls_back_to_legacy_instance_name():
    config = LakebaseConfig.from_model_config(
        _ModelConfigStub({"lakebase_instance_name": "legacy-instance"})
    )

    assert config.is_autoscaling() is False
    assert config.runtime_kwargs() == {"instance_name": "legacy-instance"}


def test_lakebase_config_uses_autoscaling_endpoint_from_model_config():
    config = LakebaseConfig.from_model_config(
        _ModelConfigStub(
            {"lakebase_autoscaling_endpoint": "projects/demo/branches/production/endpoints/ep-primary"}
        )
    )

    assert config.runtime_kwargs() == {
        "autoscaling_endpoint": "projects/demo/branches/production/endpoints/ep-primary"
    }


def test_lakebase_config_requires_no_fake_defaults(monkeypatch):
    monkeypatch.delenv("LAKEBASE_AUTOSCALING_PROJECT", raising=False)
    monkeypatch.delenv("LAKEBASE_AUTOSCALING_BRANCH", raising=False)
    monkeypatch.delenv("LAKEBASE_PROJECT", raising=False)
    monkeypatch.delenv("LAKEBASE_BRANCH", raising=False)
    monkeypatch.delenv("LAKEBASE_AUTOSCALING_ENDPOINT", raising=False)
    monkeypatch.delenv("LAKEBASE_INSTANCE_NAME", raising=False)

    config = LakebaseConfig.from_env()

    assert config.runtime_kwargs() == {}
    assert config.is_configured() is False
