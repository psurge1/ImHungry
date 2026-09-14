"""Tests for the milestone-one Bedrock model configuration."""

import agent


def test_configured_model_uses_nova_tool_calling_defaults(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeBedrockModel:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.delenv("STRANDS_MODEL_ID", raising=False)
    monkeypatch.delenv("STRANDS_MAX_TOKENS", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setattr(agent, "BedrockModel", FakeBedrockModel)

    agent._configured_model()

    assert captured == {
        "model_id": "global.amazon.nova-2-lite-v1:0",
        "region_name": "us-west-2",
        "temperature": 0,
        "max_tokens": 3000,
    }


def test_configured_model_accepts_environment_overrides(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeBedrockModel:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setenv("STRANDS_MODEL_ID", "example.model")
    monkeypatch.setenv("STRANDS_MAX_TOKENS", "1234")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(agent, "BedrockModel", FakeBedrockModel)

    agent._configured_model()

    assert captured["model_id"] == "example.model"
    assert captured["region_name"] == "us-east-1"
    assert captured["max_tokens"] == 1234
