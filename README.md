# Maestro

**Zero-gas agent orchestrator for [Tempo](https://tempo.xyz) blockchain.**

A Master Agent delegates economic tasks to Sub-Agents that hold zero gas, have scoped budgets via session keys, execute in parallel, settle atomically, and leave TIP-20 memo audit trails.

## What It Does

```
Master Agent (holds gas + master key)
    │
    ├── authorize session keys (atomic batch)
    │
    ├── Researcher Agent (nonce_key=1, $10 budget, zero gas)
    │   └── pays for market data → TIP-20 memo: {task, confidence}
    │
    ├── Analyst Agent (nonce_key=2, $5 budget, zero gas)
    │   └── pays for scoring → TIP-20 memo: {task, model, score}
    │
    ├── Settler Agent (nonce_key=3, $50 budget, zero gas)
    │   └── executes final settlement → TIP-20 memo: {trade_id}
    │
    └── revoke all session keys (atomic batch)
```

All three agents execute **in parallel** (different nonce lanes), with **zero gas** (fee sponsorship), **scoped budgets** (session keys + TokenLimit), and **on-chain provenance** (TIP-20 memos).

## Tempo Primitives Used

| Primitive | How Maestro Uses It |
|-----------|-------------------|
| **Session Keys** | `AccountKeychain.authorize_key()` with per-token spending limits and expiry |
| **Fee Sponsorship** | `awaiting_fee_payer=True` — sub-agents hold zero native tokens |
| **Call Batching** | `TempoTransaction(calls=(...))` — atomic multi-payment in one tx |
| **Parallel Execution** | Different `nonce_key` per agent — no mempool blocking |
| **Scheduling** | `valid_after` / `valid_before` — native on-chain time locks |
| **TIP-20 Memos** | `transfer_with_memo()` — structured JSON provenance in every payment |

All of these are **impossible on x402, Ethereum, or Solana** without complex smart contract workarounds.

## Install

```bash
pip install maestro-tempo
```

## Quick Start

```python
from maestro import Maestro, AgentConfig

maestro = Maestro(master_key="0x...")

maestro.register_agent(AgentConfig(
    agent_id="researcher",
    key_id="0x...",
    nonce_key=1,
    budget_tokens={"0xUSDC": 10_000_000},  # $10
))

# Authorize session keys (atomic batch)
auth_tx = maestro.build_authorize_tx()

# Build parallel agent tasks
tx, task_id = maestro.build_agent_task(
    agent_id="researcher",
    token_address="0xUSDC",
    payments=[{"to": "0xRecipient", "amount": 1_000_000, "memo_extra": {"source": "api"}}],
)

# Revoke when done
revoke_tx = maestro.build_revoke_tx()
```

## CLI Demo

```bash
maestro  # runs the full lifecycle demo
```

## Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## License

MIT
