"""reasoning_effort wiring: effective_provider, client payload, preset tiers."""

from hestia.actions import effective_provider
from hestia.providers.base import REASONING_EFFORTS, OpenAIClient
from hestia.registry.models import AgentConfig, Provider
from hestia.routers.agents import PRESETS


def _provider():
    return Provider(
        name="go", base_url="https://opencode.ai/zen/go", api_key="k", model="deepseek-v4.1-flash"
    )


def test_effective_provider_carries_effort():
    agent = AgentConfig(
        name="mimo", provider_id=1, model="mimo-v2.5", reasoning_effort="high"
    )
    eff = effective_provider(agent, _provider())
    assert eff.model == "mimo-v2.5"
    assert getattr(eff, "reasoning_effort", None) == "high"
    assert eff.base_url == "https://opencode.ai/zen/go"

    plain = effective_provider(AgentConfig(name="main", provider_id=1), _provider())
    assert getattr(plain, "reasoning_effort", None) is None


def test_effective_provider_preserves_effort_without_agent():
    effective = effective_provider(
        AgentConfig(name="mimo", provider_id=1, model="mimo-v2.5", reasoning_effort="low"),
        _provider(),
    )
    twice = effective_provider(None, effective)
    assert getattr(twice, "reasoning_effort", None) == "low"


def test_payload_includes_effort_only_when_set():
    base = dict(base_url="https://opencode.ai/zen/go", api_key="k", model="mimo-v2.5")
    assert "reasoning_effort" not in OpenAIClient(**base)._payload([])
    payload = OpenAIClient(**base, reasoning_effort="max")._payload(
        [], tools=[{"type": "function"}]
    )
    assert payload["reasoning_effort"] == "max"
    assert payload["tools"]


def test_presets_use_valid_efforts():
    for name, preset in PRESETS.items():
        assert preset.get("reasoning_effort") in REASONING_EFFORTS, name
