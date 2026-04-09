"""Tests for Maestro orchestrator — full lifecycle."""

import time

import pytest
from pytempo import TempoTransaction, Call
from mpp.methods.tempo import TempoAccount

from maestro.types import AgentConfig, TaskResult, MaestroConfig
from maestro.orchestrator import Maestro


USDC = "0x" + "00" * 20
RECIPIENT = "0x" + "dd" * 20
MASTER_KEY = "0x" + "ab" * 32


def make_agent(agent_id: str, nonce_key: int, budget: int = 10_000_000) -> AgentConfig:
    key = TempoAccount.from_key("0x" + f"{nonce_key:02x}" * 32)
    return AgentConfig(
        agent_id=agent_id, key_id=key.address, nonce_key=nonce_key,
        budget_tokens={USDC: budget},
    )


class TestMaestroInit:

    def test_creates_master_account(self):
        m = Maestro(MASTER_KEY)
        assert m.master_address.startswith("0x")
        assert len(m.master_address) == 42

    def test_master_address_deterministic(self):
        m1 = Maestro(MASTER_KEY)
        m2 = Maestro(MASTER_KEY)
        assert m1.master_address == m2.master_address

    def test_custom_config(self):
        config = MaestroConfig(chain_id=1)
        m = Maestro(MASTER_KEY, config)
        assert m.config.chain_id == 1


class TestAgentRegistration:

    def test_register_and_retrieve(self):
        m = Maestro(MASTER_KEY)
        agent = make_agent("a1", 1)
        m.register_agent(agent)
        assert m.keychain.get_agent("a1") == agent

    def test_register_multiple(self):
        m = Maestro(MASTER_KEY)
        m.register_agent(make_agent("a1", 1))
        m.register_agent(make_agent("a2", 2))
        m.register_agent(make_agent("a3", 3))
        assert len(m.keychain.agents) == 3


class TestAuthorize:

    def test_build_authorize_tx(self):
        m = Maestro(MASTER_KEY)
        m.register_agent(make_agent("a1", 1))
        m.register_agent(make_agent("a2", 2))
        tx = m.build_authorize_tx()
        assert isinstance(tx, TempoTransaction)
        assert len(tx.calls) == 2  # one per agent

    def test_authorize_tx_not_sponsored(self):
        """Authorize tx is sent by master directly — no sponsorship needed."""
        m = Maestro(MASTER_KEY)
        m.register_agent(make_agent("a1", 1))
        tx = m.build_authorize_tx()
        assert tx.awaiting_fee_payer is False

    def test_authorize_tx_uses_nonce_key_zero(self):
        m = Maestro(MASTER_KEY)
        m.register_agent(make_agent("a1", 1))
        tx = m.build_authorize_tx()
        assert tx.nonce_key == 0  # master's lane


class TestRevoke:

    def test_revoke_single_agent(self):
        m = Maestro(MASTER_KEY)
        m.register_agent(make_agent("a1", 1))
        m.register_agent(make_agent("a2", 2))
        tx = m.build_revoke_agent_tx("a1")
        assert len(tx.calls) == 1

    def test_revoke_all(self):
        m = Maestro(MASTER_KEY)
        m.register_agent(make_agent("a1", 1))
        m.register_agent(make_agent("a2", 2))
        m.register_agent(make_agent("a3", 3))
        tx = m.build_revoke_tx()
        assert len(tx.calls) == 3

    def test_revoke_nonexistent_raises(self):
        m = Maestro(MASTER_KEY)
        with pytest.raises(KeyError):
            m.build_revoke_agent_tx("ghost")


class TestAgentTasks:

    def test_build_agent_task(self):
        m = Maestro(MASTER_KEY)
        m.register_agent(make_agent("a1", 1))
        tx, task_id = m.build_agent_task(
            "a1", USDC, [{"to": RECIPIENT, "amount": 1000}],
        )
        assert isinstance(tx, TempoTransaction)
        assert task_id.startswith("task-")
        assert tx.awaiting_fee_payer is True
        assert tx.nonce_key == 1

    def test_custom_task_id(self):
        m = Maestro(MASTER_KEY)
        m.register_agent(make_agent("a1", 1))
        _, task_id = m.build_agent_task(
            "a1", USDC, [{"to": RECIPIENT, "amount": 100}], task_id="custom-id",
        )
        assert task_id == "custom-id"

    def test_multi_payment_task(self):
        m = Maestro(MASTER_KEY)
        m.register_agent(make_agent("a1", 1))
        tx, _ = m.build_agent_task(
            "a1", USDC,
            [{"to": RECIPIENT, "amount": i * 100} for i in range(4)],
        )
        assert len(tx.calls) == 4


class TestEmptyPayments:

    def test_empty_payments_rejected(self):
        m = Maestro("0x" + "ab" * 32)
        key = TempoAccount.from_key("0x" + "01" * 32)
        m.register_agent(AgentConfig(agent_id="a", key_id=key.address, nonce_key=1, budget_tokens={"0x" + "20" * 20: 1000000}))
        with pytest.raises(ValueError, match="payments must not be empty"):
            m.build_agent_task("a", "0x" + "20" * 20, [])


class TestParallelTasks:

    def test_build_parallel_3_agents(self):
        m = Maestro(MASTER_KEY)
        m.register_agent(make_agent("a1", 1))
        m.register_agent(make_agent("a2", 2))
        m.register_agent(make_agent("a3", 3))

        tasks = [
            {"agent_id": "a1", "payments": [{"to": RECIPIENT, "amount": 100}]},
            {"agent_id": "a2", "payments": [{"to": RECIPIENT, "amount": 200}]},
            {"agent_id": "a3", "payments": [{"to": RECIPIENT, "amount": 300}]},
        ]
        results = m.build_parallel_tasks(tasks, USDC)
        assert len(results) == 3

        nonce_keys = {tx.nonce_key for tx, _ in results}
        assert nonce_keys == {1, 2, 3}  # all different lanes

    def test_all_parallel_tasks_sponsored(self):
        m = Maestro(MASTER_KEY)
        m.register_agent(make_agent("a1", 1))
        m.register_agent(make_agent("a2", 2))

        tasks = [
            {"agent_id": "a1", "payments": [{"to": RECIPIENT, "amount": 100}]},
            {"agent_id": "a2", "payments": [{"to": RECIPIENT, "amount": 200}]},
        ]
        results = m.build_parallel_tasks(tasks, USDC)
        for tx, _ in results:
            assert tx.awaiting_fee_payer is True


class TestScheduledTasks:

    def test_build_scheduled_task(self):
        m = Maestro(MASTER_KEY)
        m.register_agent(make_agent("a1", 1))

        future = int(time.time()) + 60
        tx, task_id = m.build_scheduled_task(
            "a1", USDC,
            [{"to": RECIPIENT, "amount": 5000}],
            valid_after=future,
        )
        assert tx.valid_after == future
        assert tx.valid_before is None
        assert task_id.startswith("sched-")

    def test_scheduled_with_deadline(self):
        m = Maestro(MASTER_KEY)
        m.register_agent(make_agent("a1", 1))

        future = int(time.time()) + 60
        deadline = future + 300
        tx, _ = m.build_scheduled_task(
            "a1", USDC,
            [{"to": RECIPIENT, "amount": 5000}],
            valid_after=future,
            valid_before=deadline,
        )
        assert tx.valid_after == future
        assert tx.valid_before == deadline

    def test_scheduled_is_sponsored(self):
        m = Maestro(MASTER_KEY)
        m.register_agent(make_agent("a1", 1))

        tx, _ = m.build_scheduled_task(
            "a1", USDC,
            [{"to": RECIPIENT, "amount": 100}],
            valid_after=int(time.time()) + 10,
        )
        assert tx.awaiting_fee_payer is True


class TestResults:

    def test_record_and_retrieve(self):
        m = Maestro(MASTER_KEY)
        r = TaskResult(agent_id="a1", task_id="t1", success=True)
        m.record_result(r)
        assert len(m.results) == 1
        assert m.results[0].success

    def test_multiple_results(self):
        m = Maestro(MASTER_KEY)
        for i in range(5):
            m.record_result(TaskResult(agent_id=f"a{i}", task_id=f"t{i}", success=True))
        assert len(m.results) == 5
