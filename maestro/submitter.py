"""Transaction signing and submission to Tempo RPC."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from pytempo import TempoTransaction
from mpp.methods.tempo import TempoAccount

from .types import MaestroConfig

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0


class TxSubmitter:
    """Signs and submits TempoTransactions to a Tempo RPC endpoint."""

    def __init__(
        self,
        master_account: TempoAccount,
        config: MaestroConfig | None = None,
    ):
        self.master = master_account
        self.config = config or MaestroConfig()

    async def sign_and_send(
        self,
        tx: TempoTransaction,
        *,
        fee_sponsor: bool = False,
    ) -> TxReceipt:
        """Sign a transaction and submit to RPC.

        Args:
            tx: The built TempoTransaction.
            fee_sponsor: If True, sign as fee payer (for sponsored txs).
                         If False, sign as sender.
        """
        # Auto-set nonce if not already set
        if tx.nonce == 0:
            current_nonce = await self.get_nonce(tx.nonce_key)
            tx = TempoTransaction(
                chain_id=tx.chain_id,
                calls=tx.calls,
                nonce_key=tx.nonce_key,
                nonce=current_nonce,
                gas_limit=tx.gas_limit,
                max_fee_per_gas=tx.max_fee_per_gas,
                max_priority_fee_per_gas=tx.max_priority_fee_per_gas,
                awaiting_fee_payer=tx.awaiting_fee_payer,
                valid_after=tx.valid_after,
                valid_before=tx.valid_before,
                fee_token=tx.fee_token,
            )

        # Sign
        signed = tx.sign(self.master.private_key, for_fee_payer=fee_sponsor)
        raw_bytes = signed.encode()
        raw_hex = "0x" + raw_bytes.hex()

        # Submit
        tx_hash = await self._send_raw(raw_hex)
        logger.info(f"Submitted tx: {tx_hash}")

        # Wait for receipt
        receipt = await self._wait_for_receipt(tx_hash)
        return receipt

    async def estimate_gas(self, tx: TempoTransaction) -> int:
        """Estimate gas for a transaction."""
        req = tx.to_estimate_gas_request(
            sender=self.master.address,
        )
        result = await self._rpc_call("eth_estimateGas", [req, "latest"])
        return int(result, 16)

    async def get_nonce(self, nonce_key: int = 0) -> int:
        """Get the current nonce for a nonce_key."""
        # For Tempo, we query the nonce manager contract
        # Simple approach: use eth_getTransactionCount for nonce_key=0
        result = await self._rpc_call(
            "eth_getTransactionCount",
            [self.master.address, "latest"],
        )
        return int(result, 16)

    async def get_balance(self, token_address: str, account: str | None = None) -> int:
        """Get TIP-20 token balance in base units."""
        account = account or self.master.address
        # balanceOf(address) selector: 0x70a08231
        addr_padded = account.lower().replace("0x", "").zfill(64)
        data = "0x70a08231" + addr_padded
        result = await self._rpc_call(
            "eth_call",
            [{"to": token_address, "data": data}, "latest"],
        )
        return int(result, 16)

    async def fund_address(self, address: str) -> list[str]:
        """Fund an address with testnet stablecoins via tempo_fundAddress."""
        result = await self._rpc_call("tempo_fundAddress", [address])
        return result

    async def _send_raw(self, raw_hex: str) -> str:
        """Send a raw signed transaction."""
        return await self._rpc_call("eth_sendRawTransaction", [raw_hex])

    async def _wait_for_receipt(
        self, tx_hash: str, max_attempts: int = 30, delay: float = 1.0
    ) -> "TxReceipt":
        """Poll for transaction receipt."""
        import asyncio
        for _ in range(max_attempts):
            result = await self._rpc_call(
                "eth_getTransactionReceipt", [tx_hash], allow_null=True,
            )
            if result is not None:
                status = int(result.get("status", "0x0"), 16)
                return TxReceipt(
                    tx_hash=tx_hash,
                    success=status == 1,
                    block_number=int(result.get("blockNumber", "0x0"), 16),
                    gas_used=int(result.get("gasUsed", "0x0"), 16),
                    raw=result,
                )
            await asyncio.sleep(delay)

        return TxReceipt(
            tx_hash=tx_hash, success=False, error="Receipt timeout",
        )

    async def _rpc_call(
        self, method: str, params: list[Any], allow_null: bool = False,
    ) -> Any:
        """Make a JSON-RPC call to the Tempo node."""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        }
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(self.config.rpc_url, json=payload)
            response.raise_for_status()
            data = response.json()

        if "error" in data:
            error = data["error"]
            msg = error.get("message", str(error))
            raise RpcError(method, msg, error)

        result = data.get("result")
        if result is None and not allow_null:
            raise RpcError(method, "null result", data)
        return result


class TxReceipt:
    """Result of a submitted transaction."""

    def __init__(
        self,
        tx_hash: str,
        success: bool = False,
        block_number: int = 0,
        gas_used: int = 0,
        error: str = "",
        raw: dict[str, Any] | None = None,
    ):
        self.tx_hash = tx_hash
        self.success = success
        self.block_number = block_number
        self.gas_used = gas_used
        self.error = error
        self.raw = raw or {}

    def __repr__(self) -> str:
        status = "SUCCESS" if self.success else "FAILED"
        return f"TxReceipt({status}, hash={self.tx_hash[:18]}..., block={self.block_number})"

    @property
    def explorer_url(self) -> str:
        return f"https://explore.moderato.tempo.xyz/tx/{self.tx_hash}"


class RpcError(Exception):
    """RPC call failed."""

    def __init__(self, method: str, message: str, data: Any = None):
        self.method = method
        self.data = data
        super().__init__(f"RPC {method}: {message}")
