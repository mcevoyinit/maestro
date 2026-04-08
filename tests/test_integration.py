"""Integration tests — full lifecycle with real pytempo objects."""

import time

from pytempo import TempoTransaction, Call
from mpp.methods.tempo import TempoAccount

from maestro import Maestro, AgentConfig, TaskResult, MaestroConfig


USDC = "0x" + "00" * 20
MASTER_KEY = "0x" + "ab" * 32


def make_agent(agent_id: str, nonce_key: int, budget: int = 10_000_000) -> AgentConfig:
    key = TempoAccount.from_key("0x" + f"{nonce_key:02x}" * 32)
    return AgentConfig(
        agent_id=agent_id, key_id=key.address, nonce_key=nonce_key,
        budget_tokens={USDC: budget},
    )


class TestFullLifecycle:
    """End-to-end: register → authorize → tasks → schedule → revoke."""

    def test_three_agent_lifecycle(self):
        maestro = Maestro(MASTER_KEY)

        # Register 3 agents
        agents = [make_agent("researcher", 1), make_agent("analyst", 2), make_agent("settler", 3)]
        for a in agents:
            maestro.register_agent(a)
        assert len(maestro.keychain.agents) == 3

        # Authorize all (atomic batch)
        auth_tx = maestro.build_authorize_tx()
        assert isinstance(auth_tx, TempoTransaction)
        assert len(auth_tx.calls) == 3
        assert auth_tx.awaiting_fee_payer is False  # master sends directly

        # Parallel tasks
        recipient = TempoAccount.from_key("0x" + "dd" * 32).address
        tasks = [
            {"agent_id": "researcher", "payments": [{"to": recipient, "amount": 1_000_000}]},
            {"agent_id": "analyst", "payments": [{"to": recipient, "amount": 500_000}]},
            {"agent_id": "settler", "payments": [
                {"to": recipient, "amount": 10_000_000, "memo_extra": {"trade": "OTC-1"}},
                {"to": recipient, "amount": 5_000_000, "memo_extra": {"type": "fee"}},
            ]},
        ]
        parallel = maestro.build_parallel_tasks(tasks, USDC)
        assert len(parallel) == 3

        # Verify parallel execution lanes
        nonce_keys = sorted(tx.nonce_key for tx, _ in parallel)
        assert nonce_keys == [1, 2, 3]

        # Verify all sponsored
        for tx, task_id in parallel:
            assert tx.awaiting_fee_payer is True

        # Settler has 2 calls (batch)
        settler_tx = [tx for tx, _ in parallel if tx.nonce_key == 3][0]
        assert len(settler_tx.calls) == 2

        # Scheduled task
        future = int(time.time()) + 60
        sched_tx, sched_id = maestro.build_scheduled_task(
            "settler", USDC,
            [{"to": recipient, "amount": 25_000_000}],
            valid_after=future, valid_before=future + 300,
        )
        assert sched_tx.valid_after == future
        assert sched_tx.valid_before == future + 300
        assert sched_tx.awaiting_fee_payer is True

        # Revoke researcher only
        revoke_one = maestro.build_revoke_agent_tx("researcher")
        assert len(revoke_one.calls) == 1

        # Revoke all remaining
        revoke_all = maestro.build_revoke_tx()
        assert len(revoke_all.calls) == 3

    def test_session_key_addresses_are_valid(self):
        """All agent key_ids must be valid Ethereum addresses."""
        for nk in [1, 2, 3, 4, 5]:
            agent = make_agent(f"agent-{nk}", nk)
            assert agent.key_id.startswith("0x")
            assert len(agent.key_id) == 42

    def test_different_agents_different_keys(self):
        agents = [make_agent(f"a{i}", i) for i in range(1, 6)]
        key_ids = {a.key_id for a in agents}
        assert len(key_ids) == 5  # all unique

    def test_memo_hashes_in_batch(self):
        """Each payment in a batch has a unique memo hash."""
        maestro = Maestro(MASTER_KEY)
        maestro.register_agent(make_agent("a1", 1))

        recipient = TempoAccount.from_key("0x" + "ee" * 32).address
        tx, _ = maestro.build_agent_task(
            "a1", USDC,
            [
                {"to": recipient, "amount": 100, "memo_extra": {"idx": 0}},
                {"to": recipient, "amount": 200, "memo_extra": {"idx": 1}},
                {"to": recipient, "amount": 300, "memo_extra": {"idx": 2}},
            ],
        )
        assert len(tx.calls) == 3
        # Each call has different calldata (different memo hashes)
        calldatas = [c.data for c in tx.calls]
        assert len(set(calldatas)) == 3  # all unique

    def test_tx_can_be_encoded(self):
        """Prove the transaction can be serialized (not just constructed)."""
        maestro = Maestro(MASTER_KEY)
        maestro.register_agent(make_agent("a1", 1))

        tx, _ = maestro.build_agent_task(
            "a1", USDC,
            [{"to": "0x" + "dd" * 20, "amount": 1000}],
        )
        # encode() produces RLP bytes — proves tx is structurally valid
        encoded = tx.encode()
        assert isinstance(encoded, bytes)
        assert len(encoded) > 0

    def test_tx_has_correct_type(self):
        """TempoTransaction should be type 0x76."""
        maestro = Maestro(MASTER_KEY)
        maestro.register_agent(make_agent("a1", 1))
        tx, _ = maestro.build_agent_task(
            "a1", USDC, [{"to": "0x" + "dd" * 20, "amount": 100}],
        )
        assert tx.TRANSACTION_TYPE == 0x76
