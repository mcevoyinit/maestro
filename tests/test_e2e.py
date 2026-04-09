"""End-to-end blackbox tests for Maestro.

Full lifecycle: create orchestrator → register agents → authorize keys →
build parallel tasks → schedule → revoke → encode everything to bytes.
No mocks. Real pytempo/pympp objects throughout.
"""

import time

import pytest
from mpp.methods.tempo import TempoAccount
from pytempo import TempoTransaction

from maestro import Maestro, AgentConfig, MaestroConfig
from maestro.executor import SponsoredExecutor, memo_hash


# ── Constants ─────────────────────────────────────────────────

MASTER_KEY = "0x" + "ab" * 32
USDC = "0x20C0000000000000000000000000000000000000"
RECIPIENT = "0x" + "dd" * 20


def make_maestro() -> tuple:
    """Create a Maestro with 3 agents, return (maestro, agent_configs)."""
    m = Maestro(MASTER_KEY)
    agents = []
    for name, nonce, budget in [
        ("researcher", 1, 5_000_000),
        ("analyst", 2, 10_000_000),
        ("settler", 3, 50_000_000),
    ]:
        key = TempoAccount.from_key("0x" + f"{nonce:02x}" * 32)
        agent = AgentConfig(
            agent_id=name,
            key_id=key.address,
            nonce_key=nonce,
            budget_tokens={USDC: budget},
            description=f"Agent {name}",
        )
        m.register_agent(agent)
        agents.append(agent)
    return m, agents


class TestFullLifecycle:
    """Complete orchestrator lifecycle — no mocks, real TempoTransactions."""

    def test_master_address_derived(self):
        m = Maestro(MASTER_KEY)
        assert m.master_address.startswith("0x")
        assert len(m.master_address) == 42

    def test_register_3_agents(self):
        m, agents = make_maestro()
        assert len(m.keychain.agents) == 3

    def test_authorize_tx_is_atomic_batch(self):
        m, _ = make_maestro()
        tx = m.build_authorize_tx()

        assert isinstance(tx, TempoTransaction)
        assert len(tx.calls) == 3  # one authorize_key per agent
        assert tx.awaiting_fee_payer is False  # master sends directly
        assert tx.nonce_key == 0
        assert tx.chain_id == 4217

        # Must serialize to valid bytes
        encoded = tx.encode()
        assert isinstance(encoded, bytes)
        assert len(encoded) > 0
        assert encoded[0] == 0x76  # TempoTransaction type

    def test_parallel_tasks_use_separate_nonce_lanes(self):
        m, _ = make_maestro()
        tasks = [
            {"agent_id": "researcher", "payments": [{"to": RECIPIENT, "amount": 100_000, "memo_extra": {"source": "api"}}]},
            {"agent_id": "analyst", "payments": [{"to": RECIPIENT, "amount": 200_000, "memo_extra": {"model": "v2"}}]},
            {"agent_id": "settler", "payments": [
                {"to": RECIPIENT, "amount": 1_000_000, "memo_extra": {"trade": "OTC-1"}},
                {"to": RECIPIENT, "amount": 500_000, "memo_extra": {"trade": "OTC-1", "type": "fee"}},
            ]},
        ]
        parallel_txs = m.build_parallel_tasks(tasks, USDC)

        assert len(parallel_txs) == 3
        nonce_keys = sorted(tx.nonce_key for tx, _ in parallel_txs)
        assert nonce_keys == [1, 2, 3]

        for tx, task_id in parallel_txs:
            assert tx.awaiting_fee_payer is True  # sponsored
            assert tx.chain_id == 4217
            encoded = tx.encode()
            assert isinstance(encoded, bytes) and len(encoded) > 0

        # Settler has 2 payments → 2 calls in one batch
        settler_tx = [tx for tx, _ in parallel_txs if tx.nonce_key == 3][0]
        assert len(settler_tx.calls) == 2

    def test_scheduled_task(self):
        m, _ = make_maestro()
        future = int(time.time()) + 60

        tx, task_id = m.build_scheduled_task(
            agent_id="settler",
            token_address=USDC,
            payments=[{"to": RECIPIENT, "amount": 25_000_000, "memo_extra": {"type": "scheduled"}}],
            valid_after=future,
            valid_before=future + 300,
        )

        assert tx.valid_after == future
        assert tx.valid_before == future + 300
        assert tx.awaiting_fee_payer is True
        assert task_id.startswith("sched-")
        assert tx.encode()  # serializes

    def test_revoke_one_agent(self):
        m, _ = make_maestro()
        tx = m.build_revoke_agent_tx("researcher")

        assert len(tx.calls) == 1
        assert tx.awaiting_fee_payer is False
        assert tx.encode()

    def test_revoke_all_agents(self):
        m, _ = make_maestro()
        tx = m.build_revoke_tx()

        assert len(tx.calls) == 3
        assert tx.awaiting_fee_payer is False
        assert tx.encode()

    def test_single_agent_task(self):
        m, _ = make_maestro()
        tx, task_id = m.build_agent_task(
            agent_id="researcher",
            token_address=USDC,
            payments=[{"to": RECIPIENT, "amount": 20_000, "memo_extra": {"tier": "pro"}}],
        )

        assert tx.awaiting_fee_payer is True
        assert tx.nonce_key == 1  # researcher's lane
        assert len(tx.calls) == 1
        assert tx.encode()


class TestMemoHash:
    """memo_hash produces deterministic 32-byte SHA-256."""

    def test_deterministic(self):
        data = {"agent": "researcher", "task": "fetch", "confidence": 0.92}
        h1 = memo_hash(data)
        h2 = memo_hash(data)
        assert h1 == h2

    def test_exactly_32_bytes(self):
        h = memo_hash({"x": 1})
        assert isinstance(h, bytes)
        assert len(h) == 32

    def test_different_data_different_hash(self):
        h1 = memo_hash({"a": 1})
        h2 = memo_hash({"a": 2})
        assert h1 != h2

    def test_key_order_irrelevant(self):
        """sort_keys=True makes key order not matter."""
        h1 = memo_hash({"b": 2, "a": 1})
        h2 = memo_hash({"a": 1, "b": 2})
        assert h1 == h2


class TestKeyIdValidation:
    """key_id must be a valid 42-char hex address."""

    def test_valid_key_id_accepted(self):
        key = TempoAccount.from_key("0x" + "01" * 32)
        agent = AgentConfig(
            agent_id="valid",
            key_id=key.address,
            nonce_key=1,
            budget_tokens={USDC: 1_000_000},
        )
        assert agent.key_id == key.address

    def test_32_byte_key_id_rejected(self):
        bad_key_id = "0x" + "01" * 32  # 32 bytes, not 20
        with pytest.raises(ValueError):
            AgentConfig(
                agent_id="bad",
                key_id=bad_key_id,
                nonce_key=1,
                budget_tokens={USDC: 1_000_000},
            )

    def test_empty_payments_rejected(self):
        m, _ = make_maestro()
        with pytest.raises(ValueError, match="payments must not be empty"):
            m.build_agent_task("researcher", USDC, [])


class TestTransactionProperties:
    """Verify structural properties of all generated transactions."""

    def test_all_txs_are_type_0x76(self):
        m, _ = make_maestro()
        txs = [
            m.build_authorize_tx(),
            m.build_revoke_tx(),
            m.build_revoke_agent_tx("researcher"),
        ]
        task_tx, _ = m.build_agent_task("analyst", USDC, [
            {"to": RECIPIENT, "amount": 100_000, "memo_extra": {"test": True}}
        ])
        txs.append(task_tx)

        for tx in txs:
            assert tx.TRANSACTION_TYPE == 0x76
            encoded = tx.encode()
            assert encoded[0] == 0x76

    def test_authorize_and_revoke_are_inverse(self):
        m, _ = make_maestro()
        auth = m.build_authorize_tx()
        revoke = m.build_revoke_tx()
        assert len(auth.calls) == len(revoke.calls) == 3
