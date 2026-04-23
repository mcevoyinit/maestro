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


def make_tx(
    nonce_key: int,
    nonce: int = 0,
    *,
    sender_address: str | None = None,
    awaiting_fee_payer: bool = False,
) -> TempoTransaction:
    return TempoTransaction(
        chain_id=4217,
        calls=(Call(to=RECIPIENT, value=0, data=b""),),
        nonce_key=nonce_key,
        nonce=nonce,
        gas_limit=100_000,
        max_fee_per_gas=25_000_000_000,
        max_priority_fee_per_gas=1_000_000_000,
        awaiting_fee_payer=awaiting_fee_payer,
        sender_address=sender_address,
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
        submitter = make_submitter()
        tx = make_tx(nonce_key=1, nonce=0)

        captured_raw = {}

        async def capture_raw(raw_hex: str) -> str:
            captured_raw["raw"] = raw_hex
            return "0x" + "ab" * 32

        async def fake_wait_for_receipt(tx_hash, max_attempts=30, delay=1.0):
            from maestro.submitter import TxReceipt
            return TxReceipt(tx_hash=tx_hash, success=True, explorer_base="")

        monkeypatch.setattr(submitter, "_send_raw", capture_raw)
        monkeypatch.setattr(submitter, "_wait_for_receipt", fake_wait_for_receipt)

        await submitter.sign_and_send(tx, nonce=42)

        # The signed bytes must encode the explicit nonce we passed, not lane 0.
        # Decode just enough to prove the nonce value survived the pipeline.
        signed = TempoTransaction(
            chain_id=4217,
            calls=(Call(to=RECIPIENT, value=0, data=b""),),
            nonce_key=1,
            nonce=42,
            gas_limit=100_000,
            max_fee_per_gas=25_000_000_000,
            max_priority_fee_per_gas=1_000_000_000,
        ).sign(MASTER_KEY, for_fee_payer=False)
        assert captured_raw["raw"] == "0x" + signed.encode().hex()


class TestSignAndSendSponsored:

    @pytest.mark.asyncio
    async def test_fee_sponsor_true_changes_signed_bytes(self, monkeypatch):
        # Signing a tx as fee-payer must produce different raw bytes than
        # signing as sender. Same tx in, two signed outputs out.
        submitter = make_submitter()
        tx = make_tx(
            nonce_key=0,
            nonce=5,
            awaiting_fee_payer=True,
            sender_address=submitter.master.address,
        )

        captures = []

        async def capture_raw(raw_hex: str) -> str:
            captures.append(raw_hex)
            return "0x" + "ab" * 32

        async def fake_wait_for_receipt(tx_hash, max_attempts=30, delay=1.0):
            from maestro.submitter import TxReceipt
            return TxReceipt(tx_hash=tx_hash, success=True, explorer_base="")

        monkeypatch.setattr(submitter, "_send_raw", capture_raw)
        monkeypatch.setattr(submitter, "_wait_for_receipt", fake_wait_for_receipt)

        await submitter.sign_and_send(tx, fee_sponsor=False)
        await submitter.sign_and_send(tx, fee_sponsor=True)

        assert len(captures) == 2
        assert captures[0] != captures[1], "fee_sponsor flag had no effect on signed output"
