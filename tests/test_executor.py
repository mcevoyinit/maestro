"""Tests for SponsoredExecutor — transaction building."""

import json

from pytempo import TempoTransaction, Call
from mpp.methods.tempo import TempoAccount

from maestro.types import AgentConfig, MaestroConfig
from maestro.executor import SponsoredExecutor, memo_hash


USDC = "0x" + "00" * 20
RECIPIENT = "0x" + "dd" * 20


def make_agent(agent_id: str, nonce_key: int) -> AgentConfig:
    key = TempoAccount.from_key("0x" + f"{nonce_key:02x}" * 32)
    return AgentConfig(
        agent_id=agent_id, key_id=key.address, nonce_key=nonce_key,
        budget_tokens={USDC: 10_000_000},
    )


class TestMemoHash:

    def test_returns_32_bytes(self):
        h = memo_hash({"task": "t1", "agent": "a1"})
        assert len(h) == 32

    def test_deterministic(self):
        h1 = memo_hash({"a": 1, "b": 2})
        h2 = memo_hash({"b": 2, "a": 1})  # keys sorted
        assert h1 == h2

    def test_different_data_different_hash(self):
        h1 = memo_hash({"a": 1})
        h2 = memo_hash({"a": 2})
        assert h1 != h2


class TestSponsoredTx:

    def test_build_sponsored_tx(self):
        executor = SponsoredExecutor()
        agent = make_agent("a1", 1)
        call = executor.build_transfer_call(USDC, RECIPIENT, 1000)
        tx = executor.build_sponsored_tx(agent, (call,))

        assert isinstance(tx, TempoTransaction)
        assert tx.awaiting_fee_payer is True
        assert tx.nonce_key == 1
        assert tx.chain_id == 42429
        assert len(tx.calls) == 1

    def test_nonce_key_matches_agent(self):
        executor = SponsoredExecutor()
        for nk in [1, 2, 3, 10, 99]:
            agent = make_agent(f"a{nk}", nk)
            call = executor.build_transfer_call(USDC, RECIPIENT, 100)
            tx = executor.build_sponsored_tx(agent, (call,))
            assert tx.nonce_key == nk

    def test_scheduled_tx(self):
        executor = SponsoredExecutor()
        agent = make_agent("a1", 1)
        call = executor.build_transfer_call(USDC, RECIPIENT, 1000)
        tx = executor.build_sponsored_tx(
            agent, (call,), valid_after=1000000, valid_before=2000000,
        )
        assert tx.valid_after == 1000000
        assert tx.valid_before == 2000000


class TestBatchTx:

    def test_single_call_batch(self):
        executor = SponsoredExecutor()
        call = executor.build_transfer_call(USDC, RECIPIENT, 500)
        tx = executor.build_batch_tx((call,))
        assert len(tx.calls) == 1
        assert tx.awaiting_fee_payer is True

    def test_multi_call_batch(self):
        executor = SponsoredExecutor()
        calls = tuple(
            executor.build_transfer_call(USDC, RECIPIENT, i * 100)
            for i in range(5)
        )
        tx = executor.build_batch_tx(calls)
        assert len(tx.calls) == 5

    def test_unsponsored_batch(self):
        executor = SponsoredExecutor()
        call = executor.build_transfer_call(USDC, RECIPIENT, 100)
        tx = executor.build_batch_tx((call,), sponsored=False)
        assert tx.awaiting_fee_payer is False


class TestTransferCalls:

    def test_build_transfer_call(self):
        call = SponsoredExecutor.build_transfer_call(USDC, RECIPIENT, 1000000)
        assert isinstance(call, Call)

    def test_build_memo_transfer_call(self):
        call = SponsoredExecutor.build_memo_transfer_call(
            USDC, RECIPIENT, 1000000, {"task": "t1", "agent": "a1"},
        )
        assert isinstance(call, Call)

    def test_memo_call_different_from_plain(self):
        plain = SponsoredExecutor.build_transfer_call(USDC, RECIPIENT, 1000)
        memo = SponsoredExecutor.build_memo_transfer_call(
            USDC, RECIPIENT, 1000, {"x": 1},
        )
        assert plain.data != memo.data  # memo adds hash to calldata


class TestAgentTaskTx:

    def test_build_single_payment(self):
        executor = SponsoredExecutor()
        agent = make_agent("a1", 1)
        tx = executor.build_agent_task_tx(
            agent, USDC,
            payments=[{"to": RECIPIENT, "amount": 1000}],
            task_id="task-001",
        )
        assert len(tx.calls) == 1
        assert tx.awaiting_fee_payer is True
        assert tx.nonce_key == 1

    def test_build_multi_payment(self):
        executor = SponsoredExecutor()
        agent = make_agent("a1", 1)
        payments = [
            {"to": RECIPIENT, "amount": 1000, "memo_extra": {"type": "data"}},
            {"to": RECIPIENT, "amount": 2000, "memo_extra": {"type": "fee"}},
            {"to": RECIPIENT, "amount": 3000},
        ]
        tx = executor.build_agent_task_tx(agent, USDC, payments, "task-002")
        assert len(tx.calls) == 3

    def test_custom_config(self):
        config = MaestroConfig(chain_id=1, gas_limit=100_000)
        executor = SponsoredExecutor(config)
        agent = make_agent("a1", 1)
        tx = executor.build_agent_task_tx(
            agent, USDC, [{"to": RECIPIENT, "amount": 100}], "t1",
        )
        assert tx.chain_id == 1
        assert tx.gas_limit == 100_000
