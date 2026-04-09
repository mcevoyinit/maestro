"""Tests for Maestro core types."""

import json
import time

import pytest

from maestro.types import AgentConfig, TaskResult, MaestroConfig


# Valid 42-char Ethereum address for tests
VALID_ADDR = "0x" + "ab" * 20


class TestAgentConfig:

    def test_create_with_defaults(self):
        agent = AgentConfig(agent_id="test", key_id=VALID_ADDR, nonce_key=1)
        assert agent.agent_id == "test"
        assert agent.nonce_key == 1
        assert agent.budget_tokens == {}

    def test_create_with_budget(self):
        agent = AgentConfig(
            agent_id="a1", key_id=VALID_ADDR, nonce_key=2,
            budget_tokens={"0xUSDC": 10_000_000},
        )
        assert agent.budget_tokens["0xUSDC"] == 10_000_000

    def test_effective_expiry_default(self):
        agent = AgentConfig(agent_id="a1", key_id=VALID_ADDR, nonce_key=1)
        expiry = agent.effective_expiry()
        assert expiry > int(time.time())
        assert expiry <= int(time.time()) + 3601

    def test_effective_expiry_explicit(self):
        future = int(time.time()) + 7200
        agent = AgentConfig(agent_id="a1", key_id=VALID_ADDR, nonce_key=1, expiry=future)
        assert agent.effective_expiry() == future

    def test_frozen(self):
        agent = AgentConfig(agent_id="a1", key_id=VALID_ADDR, nonce_key=1)
        try:
            agent.agent_id = "changed"
            assert False, "Should be frozen"
        except AttributeError:
            pass

    def test_key_id_too_short_raises(self):
        with pytest.raises(ValueError, match="42 chars"):
            AgentConfig(agent_id="bad", key_id="0xabc", nonce_key=1)

    def test_key_id_too_long_raises(self):
        with pytest.raises(ValueError, match="42 chars"):
            AgentConfig(agent_id="bad", key_id="0x" + "aa" * 32, nonce_key=1)

    def test_key_id_empty_allowed(self):
        """Empty key_id skips validation (falsy check)."""
        agent = AgentConfig(agent_id="empty", key_id="", nonce_key=1)
        assert agent.key_id == ""


class TestTaskResult:

    def test_create_success(self):
        result = TaskResult(agent_id="a1", task_id="t1", success=True, tx_hash="0xabc")
        assert result.success
        assert result.tx_hash == "0xabc"

    def test_create_failure(self):
        result = TaskResult(agent_id="a1", task_id="t1", success=False, error="timeout")
        assert not result.success
        assert result.error == "timeout"

    def test_to_memo_hash_is_32_bytes(self):
        result = TaskResult(
            agent_id="researcher", task_id="task-001", success=True,
            memo_data={"confidence": 0.95, "source": "api"},
        )
        memo = result.to_memo_hash()
        assert isinstance(memo, bytes)
        assert len(memo) == 32

    def test_memo_hash_deterministic(self):
        r1 = TaskResult(agent_id="a1", task_id="t1", success=True, memo_data={"x": 1})
        r2 = TaskResult(agent_id="a1", task_id="t1", success=True, memo_data={"x": 1})
        assert r1.to_memo_hash() == r2.to_memo_hash()

    def test_memo_hash_different_data(self):
        r1 = TaskResult(agent_id="a1", task_id="t1", success=True, memo_data={"x": 1})
        r2 = TaskResult(agent_id="a1", task_id="t1", success=True, memo_data={"x": 2})
        assert r1.to_memo_hash() != r2.to_memo_hash()


class TestMaestroConfig:

    def test_defaults(self):
        config = MaestroConfig()
        assert config.chain_id == 42431
        assert config.gas_limit == 500_000
        assert config.signature_type == 2

    def test_custom_chain(self):
        config = MaestroConfig(chain_id=1)
        assert config.chain_id == 1
