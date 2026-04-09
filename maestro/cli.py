"""Maestro CLI — demonstrates the full agent lifecycle."""

from __future__ import annotations

import json
import time
import sys

from mpp.methods.tempo import TempoAccount

from .types import AgentConfig, MaestroConfig
from .orchestrator import Maestro


# Testnet USDC address (placeholder — replace with actual TIP-20 on testnet)
TESTNET_USDC = "0x" + "00" * 20


def demo_agents() -> list[AgentConfig]:
    """Create 3 specialist agents with different budgets."""
    # key_id must be an address (20 bytes) — use TempoAccount to derive
    researcher_key = TempoAccount.from_key("0x" + "11" * 32)
    analyst_key = TempoAccount.from_key("0x" + "22" * 32)
    settler_key = TempoAccount.from_key("0x" + "33" * 32)

    return [
        AgentConfig(
            agent_id="researcher",
            key_id=researcher_key.address,
            nonce_key=1,
            budget_tokens={TESTNET_USDC: 10_000_000},  # $10 USDC (6 decimals)
            description="Fetches market data and research",
        ),
        AgentConfig(
            agent_id="analyst",
            key_id=analyst_key.address,
            nonce_key=2,
            budget_tokens={TESTNET_USDC: 5_000_000},  # $5 USDC
            description="Processes and scores opportunities",
        ),
        AgentConfig(
            agent_id="settler",
            key_id=settler_key.address,
            nonce_key=3,
            budget_tokens={TESTNET_USDC: 50_000_000},  # $50 USDC
            description="Executes final settlements",
        ),
    ]


def print_header(text: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}\n")


def print_tx_info(label: str, tx) -> None:
    print(f"  {label}:")
    print(f"    chain_id:           {tx.chain_id}")
    print(f"    calls:              {len(tx.calls)}")
    print(f"    nonce_key:          {tx.nonce_key}")
    print(f"    awaiting_fee_payer: {tx.awaiting_fee_payer}")
    if tx.valid_after is not None:
        print(f"    valid_after:        {tx.valid_after}")
    if tx.valid_before is not None:
        print(f"    valid_before:       {tx.valid_before}")
    print()


def main() -> None:
    print_header("MAESTRO — Zero-Gas Agent Orchestrator")
    print("  Tempo chain: Tempo mainnet (4217)")
    print("  Protocol:    0x76 TempoTransaction")
    print("  Primitives:  session keys + fee sponsorship + batch + schedule")

    # Master wallet (demo key — NOT funded, just for structure demo)
    master_key = "0x" + "ab" * 32
    maestro = Maestro(master_key)

    print(f"\n  Master address: {maestro.master_address}")

    # ── Phase 1: Register agents ──────────────────────────────
    print_header("PHASE 1: Register Sub-Agents")

    agents = demo_agents()
    for agent in agents:
        maestro.register_agent(agent)
        budget_str = ", ".join(
            f"${amt / 1_000_000:.0f}" for amt in agent.budget_tokens.values()
        )
        print(f"  [{agent.agent_id}]")
        print(f"    nonce_key: {agent.nonce_key} (parallel lane)")
        print(f"    budget:    {budget_str} USDC")
        print(f"    role:      {agent.description}")
        print()

    # ── Phase 2: Authorize session keys ───────────────────────
    print_header("PHASE 2: Authorize Session Keys (atomic batch)")

    auth_tx = maestro.build_authorize_tx()
    print(f"  Batch transaction with {len(auth_tx.calls)} authorize_key calls")
    print(f"  ALL keys created atomically — succeed together or fail together")
    print_tx_info("authorize_all_tx", auth_tx)

    # ── Phase 3: Parallel agent tasks ─────────────────────────
    print_header("PHASE 3: Parallel Agent Tasks (sponsored, with memos)")

    recipient = "0x" + "dd" * 20  # demo recipient
    tasks = [
        {
            "agent_id": "researcher",
            "payments": [
                {
                    "to": recipient,
                    "amount": 1_000_000,  # $1
                    "memo_extra": {"source": "coingecko", "confidence": 0.92},
                },
            ],
        },
        {
            "agent_id": "analyst",
            "payments": [
                {
                    "to": recipient,
                    "amount": 500_000,  # $0.50
                    "memo_extra": {"model": "risk-v2", "score": 7.4},
                },
            ],
        },
        {
            "agent_id": "settler",
            "payments": [
                {
                    "to": recipient,
                    "amount": 10_000_000,  # $10
                    "memo_extra": {"trade_id": "OTC-001", "settlement": "final"},
                },
                {
                    "to": recipient,
                    "amount": 5_000_000,  # $5
                    "memo_extra": {"trade_id": "OTC-001", "type": "fee"},
                },
            ],
        },
    ]

    parallel_txs = maestro.build_parallel_tasks(tasks, TESTNET_USDC)

    for tx, task_id in parallel_txs:
        # find agent from tx nonce_key
        agent_id = "unknown"
        for a in agents:
            if a.nonce_key == tx.nonce_key:
                agent_id = a.agent_id
                break
        print(f"  [{agent_id}] task={task_id}")
        print(f"    nonce_key={tx.nonce_key} (parallel lane)")
        print(f"    calls={len(tx.calls)} payment(s)")
        print(f"    sponsored={tx.awaiting_fee_payer} (master pays gas)")
        print()

    print(f"  → {len(parallel_txs)} transactions ready for parallel submission")
    print(f"  → Each uses a different nonce_key — NO mempool blocking")
    print(f"  → All gas paid by master via fee sponsorship")

    # ── Phase 4: Scheduled task ───────────────────────────────
    print_header("PHASE 4: Scheduled Task (time-locked)")

    future_time = int(time.time()) + 60  # 60 seconds from now
    sched_tx, sched_id = maestro.build_scheduled_task(
        agent_id="settler",
        token_address=TESTNET_USDC,
        payments=[{
            "to": recipient,
            "amount": 25_000_000,  # $25
            "memo_extra": {"type": "scheduled_settlement", "deadline": future_time + 300},
        }],
        valid_after=future_time,
        valid_before=future_time + 300,
    )

    print(f"  task={sched_id}")
    print(f"  valid_after:  {future_time} (executes in ~60s)")
    print(f"  valid_before: {future_time + 300} (5 min deadline)")
    print_tx_info("scheduled_tx", sched_tx)

    # ── Phase 5: Revoke keys ─────────────────────────────────
    print_header("PHASE 5: Revoke Session Keys")

    # Revoke just the researcher
    revoke_one_tx = maestro.build_revoke_agent_tx("researcher")
    print(f"  Revoking [researcher] key — agent can no longer transact")
    print_tx_info("revoke_researcher_tx", revoke_one_tx)

    # Revoke all remaining
    revoke_all_tx = maestro.build_revoke_tx()
    print(f"  Revoking ALL remaining keys — {len(revoke_all_tx.calls)} revoke_key calls")
    print_tx_info("revoke_all_tx", revoke_all_tx)

    # ── Summary ──────────────────────────────────────────────
    print_header("LIFECYCLE COMPLETE")
    print("  1. ✓ Session keys authorized (atomic batch)")
    print("  2. ✓ Parallel tasks built (3 agents, 3 nonce lanes)")
    print("  3. ✓ All transactions fee-sponsored (zero-gas agents)")
    print("  4. ✓ Scheduled task with valid_after/valid_before")
    print("  5. ✓ TIP-20 memos with structured JSON provenance")
    print("  6. ✓ Session keys revoked (individual + batch)")
    print()
    print("  Primitives used: session keys, fee sponsorship, call batching,")
    print("                   parallel nonce_key, TIP-20 memo, scheduling")
    print()
    print("  All impossible on x402 / Ethereum / Solana.")
    print()


if __name__ == "__main__":
    main()
