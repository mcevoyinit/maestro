"""Fee-sponsored transaction execution with parallel nonce lanes."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pytempo import TempoTransaction, Call
from pytempo.contracts.tip20 import TIP20

from .types import AgentConfig, TaskResult, MaestroConfig


def memo_hash(data: dict[str, Any]) -> bytes:
    """Hash structured memo data into 32 bytes for TIP-20 memo field.

    The full JSON is stored off-chain. The 32-byte SHA-256 hash on-chain
    proves the payment was linked to specific task metadata.
    """
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).digest()


class SponsoredExecutor:
    """Builds fee-sponsored, parallel, batched transactions on Tempo."""

    def __init__(self, config: MaestroConfig | None = None):
        self.config = config or MaestroConfig()

    def build_sponsored_tx(
        self,
        agent: AgentConfig,
        calls: tuple[Call, ...],
        *,
        valid_after: int | None = None,
        valid_before: int | None = None,
    ) -> TempoTransaction:
        """Build a fee-sponsored transaction for a sub-agent.

        The agent's nonce_key ensures parallel execution.
        awaiting_fee_payer=True means the master will sign the fee envelope.
        """
        return TempoTransaction(
            chain_id=self.config.chain_id,
            calls=calls,
            nonce_key=agent.nonce_key,
            gas_limit=self.config.gas_limit,
            max_fee_per_gas=self.config.max_fee_per_gas,
            max_priority_fee_per_gas=self.config.max_priority_fee_per_gas,
            awaiting_fee_payer=True,
            valid_after=valid_after,
            valid_before=valid_before,
        )

    def build_batch_tx(
        self,
        calls: tuple[Call, ...],
        nonce_key: int = 0,
        *,
        sponsored: bool = True,
    ) -> TempoTransaction:
        """Build an atomic batch transaction with multiple calls.

        All calls succeed or all revert — native Tempo atomicity.
        """
        return TempoTransaction(
            chain_id=self.config.chain_id,
            calls=calls,
            nonce_key=nonce_key,
            gas_limit=self.config.gas_limit,
            max_fee_per_gas=self.config.max_fee_per_gas,
            max_priority_fee_per_gas=self.config.max_priority_fee_per_gas,
            awaiting_fee_payer=sponsored,
        )

    @staticmethod
    def build_transfer_call(
        token_address: str,
        to: str,
        amount: int,
    ) -> Call:
        """Build a TIP-20 transfer Call."""
        tip20 = TIP20(token_address)
        return tip20.transfer(to=to, amount=amount)

    @staticmethod
    def build_memo_transfer_call(
        token_address: str,
        to: str,
        amount: int,
        memo_data: dict[str, Any],
    ) -> Call:
        """Build a TIP-20 transfer with memo.

        TIP-20 memos are 32 bytes max. We encode a SHA-256 hash of the
        structured JSON metadata. The full metadata is stored off-chain
        (logs, IPFS, etc.) and the memo provides on-chain proof of linkage.
        """
        tip20 = TIP20(token_address)
        memo_bytes = memo_hash(memo_data)
        return tip20.transfer_with_memo(to=to, amount=amount, memo=memo_bytes)

    def build_agent_task_tx(
        self,
        agent: AgentConfig,
        token_address: str,
        payments: list[dict[str, Any]],
        task_id: str,
    ) -> TempoTransaction:
        """Build a complete agent task: batch of memo transfers.

        Each payment: {"to": addr, "amount": int, "memo_extra": {...}}
        """
        calls = []
        for payment in payments:
            memo = {
                "task_id": task_id,
                "agent_id": agent.agent_id,
                **payment.get("memo_extra", {}),
            }
            call = self.build_memo_transfer_call(
                token_address=token_address,
                to=payment["to"],
                amount=payment["amount"],
                memo_data=memo,
            )
            calls.append(call)

        return self.build_sponsored_tx(agent, tuple(calls))
