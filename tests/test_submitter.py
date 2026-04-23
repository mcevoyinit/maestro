"""Tests for TxSubmitter."""

import pytest
from mpp.methods.tempo import TempoAccount
from pytempo import TempoTransaction, Call

from maestro.submitter import TxSubmitter
from maestro.types import MaestroConfig


MASTER_KEY = "0x" + "11" * 32
RECIPIENT = "0x" + "dd" * 20


def make_submitter() -> TxSubmitter:
    account = TempoAccount.from_key(MASTER_KEY)
    return TxSubmitter(account, MaestroConfig())


def make_tx(nonce_key: int, nonce: int = 0) -> TempoTransaction:
    return TempoTransaction(
        chain_id=4217,
        calls=(Call(to=RECIPIENT, value=0, data=b""),),
        nonce_key=nonce_key,
        nonce=nonce,
        gas_limit=100_000,
        max_fee_per_gas=25_000_000_000,
        max_priority_fee_per_gas=1_000_000_000,
    )


class TestSubmitNonce:

    @pytest.mark.asyncio
    async def test_parallel_lane_without_explicit_nonce_raises(self):
        submitter = make_submitter()
        tx = make_tx(nonce_key=1, nonce=0)

        with pytest.raises(ValueError, match="parallel lane"):
            await submitter.sign_and_send(tx)

    @pytest.mark.asyncio
    async def test_parallel_lane_with_explicit_nonce_does_not_raise(self, monkeypatch):
        # Stub out network calls; we only care that the validation passes.
        submitter = make_submitter()
        tx = make_tx(nonce_key=1, nonce=0)

        async def fake_send_raw(raw_hex: str) -> str:
            return "0x" + "ab" * 32

        async def fake_wait_for_receipt(tx_hash, max_attempts=30, delay=1.0):
            from maestro.submitter import TxReceipt
            return TxReceipt(tx_hash=tx_hash, success=True, explorer_base="")

        monkeypatch.setattr(submitter, "_send_raw", fake_send_raw)
        monkeypatch.setattr(submitter, "_wait_for_receipt", fake_wait_for_receipt)

        receipt = await submitter.sign_and_send(tx, nonce=42)
        assert receipt.success
