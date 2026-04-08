"""Live testnet integration test.

Run with: pytest tests/test_testnet_live.py -v -s
Requires network access to rpc.moderato.tempo.xyz
"""

import pytest

from mpp.methods.tempo import TempoAccount
from pytempo import TempoTransaction
from pytempo.contracts.tip20 import TIP20
from pytempo.contracts.addresses import PATH_USD

from maestro.submitter import TxSubmitter, TxReceipt
from maestro.types import MaestroConfig

MASTER_KEY = "0x" + "ab" * 32
RECIPIENT_KEY = "0x" + "cd" * 32


@pytest.fixture
def master():
    return TempoAccount.from_key(MASTER_KEY)


@pytest.fixture
def recipient():
    return TempoAccount.from_key(RECIPIENT_KEY)


@pytest.fixture
def submitter(master):
    return TxSubmitter(master)


@pytest.fixture
def tip20():
    return TIP20(PATH_USD)


class TestTestnetLive:
    """These tests hit the real Moderato testnet."""

    @pytest.mark.asyncio
    async def test_fund_and_check_balance(self, submitter, master):
        """Fund address and verify balance is non-zero."""
        # Fund
        tx_hashes = await submitter.fund_address(master.address)
        assert len(tx_hashes) == 4  # 4 stablecoins

        # Check balance
        balance = await submitter.get_balance(PATH_USD, master.address)
        assert balance > 0, f"Expected non-zero pathUSD balance, got {balance}"
        print(f"\n  pathUSD balance: {balance / 1_000_000:.2f} USD")

    @pytest.mark.asyncio
    async def test_simple_transfer(self, submitter, master, recipient, tip20):
        """Send a real pathUSD transfer on testnet."""
        # Fund recipient too (so they exist on-chain)
        await submitter.fund_address(recipient.address)

        # Build transfer: $1 pathUSD
        call = tip20.transfer(to=recipient.address, amount=1_000_000)
        tx = TempoTransaction(
            chain_id=42431,
            calls=(call,),
            nonce_key=0,
            gas_limit=500_000,
            max_fee_per_gas=25_000_000_000,
            max_priority_fee_per_gas=1_000_000_000,
        )

        # Sign and send
        receipt = await submitter.sign_and_send(tx)
        print(f"\n  TX hash:  {receipt.tx_hash}")
        print(f"  Block:    {receipt.block_number}")
        print(f"  Gas used: {receipt.gas_used}")
        print(f"  Status:   {'SUCCESS' if receipt.success else 'FAILED'}")
        print(f"  Explorer: {receipt.explorer_url}")

        assert receipt.success, f"Transfer failed: {receipt.error}"
        assert receipt.block_number > 0
        assert receipt.gas_used > 0

    @pytest.mark.asyncio
    async def test_batch_transfer(self, submitter, master, recipient, tip20):
        """Send an atomic batch of 3 transfers in one tx."""
        calls = tuple(
            tip20.transfer(to=recipient.address, amount=(i + 1) * 100_000)
            for i in range(3)
        )
        tx = TempoTransaction(
            chain_id=42431,
            calls=calls,
            nonce_key=0,
            gas_limit=500_000,
            max_fee_per_gas=25_000_000_000,
            max_priority_fee_per_gas=1_000_000_000,
        )

        receipt = await submitter.sign_and_send(tx)
        print(f"\n  Batch TX: {receipt.tx_hash}")
        print(f"  Calls:    {len(calls)}")
        print(f"  Status:   {'SUCCESS' if receipt.success else 'FAILED'}")
        print(f"  Explorer: {receipt.explorer_url}")

        assert receipt.success, f"Batch failed: {receipt.error}"

    @pytest.mark.asyncio
    async def test_memo_transfer(self, submitter, master, recipient, tip20):
        """Send a transfer with TIP-20 memo (provenance hash)."""
        import hashlib, json
        memo_data = {"task_id": "live-test-001", "agent_id": "tester", "confidence": 0.99}
        memo_hash = hashlib.sha256(
            json.dumps(memo_data, sort_keys=True, separators=(",", ":")).encode()
        ).digest()

        call = tip20.transfer_with_memo(
            to=recipient.address, amount=500_000, memo=memo_hash,
        )
        tx = TempoTransaction(
            chain_id=42431,
            calls=(call,),
            nonce_key=0,
            gas_limit=500_000,
            max_fee_per_gas=25_000_000_000,
            max_priority_fee_per_gas=1_000_000_000,
        )

        receipt = await submitter.sign_and_send(tx)
        print(f"\n  Memo TX:  {receipt.tx_hash}")
        print(f"  Memo:     {memo_hash.hex()}")
        print(f"  Status:   {'SUCCESS' if receipt.success else 'FAILED'}")
        print(f"  Explorer: {receipt.explorer_url}")

        assert receipt.success
