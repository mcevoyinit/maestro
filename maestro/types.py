"""Core types for Maestro agent orchestration."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentConfig:
    """Configuration for a sub-agent with scoped economic permissions."""

    agent_id: str
    key_id: str  # AccountKeychain key identifier
    nonce_key: int  # parallel execution lane
    budget_tokens: dict[str, int] = field(default_factory=dict)  # token_addr -> limit (base units)
    expiry: int = 0  # unix timestamp (0 = 1 hour from creation)
    description: str = ""

    def effective_expiry(self) -> int:
        if self.expiry > 0:
            return self.expiry
        return int(time.time()) + 3600  # default 1 hour


@dataclass
class TaskResult:
    """Result of a sub-agent task execution."""

    agent_id: str
    task_id: str
    success: bool
    calls_executed: int = 0
    tx_hash: str = ""
    error: str = ""
    memo_data: dict[str, Any] = field(default_factory=dict)

    def to_memo_hash(self) -> bytes:
        """Hash task metadata into 32-byte TIP-20 memo.

        TIP-20 memos are capped at 32 bytes. We SHA-256 hash the
        full structured data; the original JSON is stored off-chain.
        """
        import hashlib
        payload = {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "success": self.success,
            **self.memo_data,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).digest()


@dataclass
class MaestroConfig:
    """Top-level orchestrator configuration."""

    chain_id: int = 42431  # Tempo Moderato testnet
    rpc_url: str = "https://rpc.moderato.tempo.xyz"
    gas_limit: int = 500_000
    max_fee_per_gas: int = 25_000_000_000  # 25 gwei (Moderato min base fee is 20 gwei)
    max_priority_fee_per_gas: int = 1_000_000_000  # 1 gwei tip
    signature_type: int = 2  # secp256k1
