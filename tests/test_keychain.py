"""Tests for KeychainManager — session key lifecycle."""

import pytest
from pytempo import Call

from mpp.methods.tempo import TempoAccount

from maestro.types import AgentConfig, MaestroConfig
from maestro.keychain import KeychainManager


USDC = "0x" + "00" * 20


def make_agent(agent_id: str, nonce_key: int, budget: int = 10_000_000) -> AgentConfig:
    """Create an agent with a valid address as key_id."""
    key = TempoAccount.from_key("0x" + f"{nonce_key:02x}" * 32)
    return AgentConfig(
        agent_id=agent_id,
        key_id=key.address,
        nonce_key=nonce_key,
        budget_tokens={USDC: budget},
    )


class TestRegister:

    def test_register_and_retrieve(self):
        km = KeychainManager()
        agent = make_agent("a1", 1)
        km.register(agent)
        assert km.get_agent("a1") == agent

    def test_register_multiple(self):
        km = KeychainManager()
        km.register(make_agent("a1", 1))
        km.register(make_agent("a2", 2))
        assert len(km.agents) == 2

    def test_get_nonexistent_raises(self):
        km = KeychainManager()
        with pytest.raises(KeyError):
            km.get_agent("ghost")

    def test_agents_returns_copy(self):
        km = KeychainManager()
        km.register(make_agent("a1", 1))
        agents_copy = km.agents
        agents_copy["a2"] = make_agent("a2", 2)
        assert len(km.agents) == 1


class TestAuthorizeCalls:

    def test_build_authorize_call_returns_call(self):
        km = KeychainManager()
        agent = make_agent("a1", 1)
        call = km.build_authorize_call(agent)
        assert isinstance(call, Call)

    def test_authorize_call_has_data(self):
        km = KeychainManager()
        agent = make_agent("a1", 1)
        call = km.build_authorize_call(agent)
        assert call.data  # non-empty calldata

    def test_authorize_without_limits(self):
        key = TempoAccount.from_key("0x" + "aa" * 32)
        agent = AgentConfig(agent_id="free", key_id=key.address, nonce_key=5)
        km = KeychainManager()
        call = km.build_authorize_call(agent)
        assert isinstance(call, Call)

    def test_build_authorize_all(self):
        km = KeychainManager()
        km.register(make_agent("a1", 1))
        km.register(make_agent("a2", 2))
        km.register(make_agent("a3", 3))
        calls = km.build_authorize_all()
        assert len(calls) == 3
        assert all(isinstance(c, Call) for c in calls)


class TestRevokeCalls:

    def test_build_revoke_call(self):
        km = KeychainManager()
        agent = make_agent("a1", 1)
        call = km.build_revoke_call(agent)
        assert isinstance(call, Call)

    def test_build_revoke_all(self):
        km = KeychainManager()
        km.register(make_agent("a1", 1))
        km.register(make_agent("a2", 2))
        calls = km.build_revoke_all()
        assert len(calls) == 2
        assert all(isinstance(c, Call) for c in calls)


class TestUpdateLimitCall:

    def test_build_update_limit(self):
        km = KeychainManager()
        agent = make_agent("a1", 1)
        call = km.build_update_limit_call(agent, USDC, 20_000_000)
        assert isinstance(call, Call)
