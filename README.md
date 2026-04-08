# Maestro

**Zero-gas agent orchestrator for [Tempo](https://tempo.xyz) blockchain.**

A Master Agent delegates economic tasks to Sub-Agents that hold zero gas, have scoped budgets via session keys, execute in parallel, settle atomically, and leave on-chain audit trails.

## The Idea

Think of Maestro like **corporate credit cards for AI agents**.

A company (master agent) issues cards (session keys) to employees (sub-agents). Each card has a spending limit, an expiry date, and vendor restrictions. The company pays the processing fees — employees never touch the company bank account. The company can cancel any card instantly. Every purchase has a receipt.

Now replace "company" with an orchestrator, "employees" with autonomous AI agents, "cards" with Tempo session keys, "processing fees" with blockchain gas, and "receipts" with TIP-20 memo hashes. That's Maestro.

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

## Why Tempo (and Why Not x402/Ethereum/Solana)

On Ethereum or Solana, achieving what Maestro does requires deploying 5+ separate smart contracts and off-chain infrastructure:

| Capability | Tempo (native) | Ethereum | x402 |
|-----------|---------------|----------|------|
| Scoped agent budgets | `AccountKeychain.authorize_key()` | Custom ERC-4337 smart wallet | Not supported |
| Zero-gas agents | `awaiting_fee_payer=True` | Separate paymaster contract | Agents need ETH/SOL |
| Parallel execution | `nonce_key` per agent | Nonce blocking (sequential) | 1 tx per request |
| Atomic multi-payment | `calls=(Call, Call, ...)` | Multicall contract needed | Not supported |
| On-chain scheduling | `valid_after` / `valid_before` | Keeper network (Chainlink) | Off-chain cron |
| Payment provenance | `TIP20.transfer_with_memo()` | No native memo field | Basic |

On Tempo, all six are parameters on a single `TempoTransaction`. No contracts to deploy, no infrastructure to run.

## Use Cases

### Autonomous Research Swarm
Deploy 10 analyst agents, each with a $5/day session key. They pay for market data APIs via [MPP](https://mpp.dev/overview), run analysis in parallel, and the settler agent executes trades — all fee-sponsored, all with on-chain audit trails.

### AI Workforce Batch Payroll
Batch monthly payments to 50 contractors in a single atomic transaction. Each payment has a TIP-20 memo linking to the invoice hash. Scheduled via `valid_after` for the 1st of the month. The company sponsors gas — recipients don't need native tokens.

### Scoped Agent Sandboxing
Testing a new AI agent? Give it a session key with a $2 `TokenLimit` and 1-hour expiry. It can experiment freely within bounds. When the hour's up or the budget's spent, the key auto-expires. Goes rogue? Revoke instantly.

### Multi-Agent Supply Chain
Agent A sources data ($0.01), Agent B processes it ($0.05), Agent C delivers the result ($0.10). All three run in parallel nonce lanes. The batch either fully settles or fully reverts — atomic guarantees without custom escrow contracts.

## Tempo Primitives Used

| Primitive | How Maestro Uses It |
|-----------|-------------------|
| **Session Keys** | `AccountKeychain.authorize_key()` with per-token spending limits and expiry |
| **Fee Sponsorship** | `awaiting_fee_payer=True` — sub-agents hold zero native tokens |
| **Call Batching** | `TempoTransaction(calls=(...))` — atomic multi-payment in one tx |
| **Parallel Execution** | Different `nonce_key` per agent — no mempool blocking |
| **Scheduling** | `valid_after` / `valid_before` — native on-chain time locks |
| **TIP-20 Memos** | `transfer_with_memo()` — SHA-256 provenance hash in every payment |

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
    key_id="0x...",      # agent's session key address
    nonce_key=1,         # parallel execution lane
    budget_tokens={"0x20C0...0000": 10_000_000},  # $10 pathUSD
))

# Authorize session keys (atomic batch)
auth_tx = maestro.build_authorize_tx()

# Build parallel agent tasks with memo provenance
tx, task_id = maestro.build_agent_task(
    agent_id="researcher",
    token_address="0x20C0...0000",  # pathUSD
    payments=[{
        "to": "0xRecipient",
        "amount": 1_000_000,
        "memo_extra": {"source": "coingecko", "confidence": 0.92},
    }],
)

# Schedule a future payment
sched_tx, sched_id = maestro.build_scheduled_task(
    agent_id="researcher",
    token_address="0x20C0...0000",
    payments=[{"to": "0xRecipient", "amount": 5_000_000}],
    valid_after=1775700000,  # unix timestamp
)

# Revoke when done
revoke_tx = maestro.build_revoke_tx()
```

## CLI Demo

```bash
maestro  # runs the full lifecycle demo
```

Shows: register 3 agents → authorize keys (atomic) → parallel tasks (3 nonce lanes) → scheduled task → revoke keys.

## Testnet

Maestro targets the Tempo Moderato testnet:

| Detail | Value |
|--------|-------|
| Chain ID | `42431` |
| RPC | `https://rpc.moderato.tempo.xyz` |
| Explorer | `https://explore.moderato.tempo.xyz` |
| Faucet | `cast rpc tempo_fundAddress <YOUR_ADDRESS> --rpc-url https://rpc.moderato.tempo.xyz` |
| Stablecoins | pathUSD, AlphaUSD, BetaUSD, ThetaUSD (1M each from faucet) |

## Contract Addresses (built into pytempo)

| Contract | Address |
|----------|---------|
| AccountKeychain | `0xaAAAaaAA00000000000000000000000000000000` |
| pathUSD (TIP-20) | `0x20C0000000000000000000000000000000000000` |
| AlphaUSD | `0x20C0000000000000000000000000000000000001` |
| Nonce Manager | `0x4e4F4E4345000000000000000000000000000000` |
| Fee Manager | `0xfeEC000000000000000000000000000000000000` |
| StablecoinDEX | `0xDEc0000000000000000000000000000000000000` |

## Part of the Tempo Python Portfolio

| Repo | Role | Tests |
|------|------|-------|
| [**Parley**](https://github.com/mcevoyinit/parley) | Negotiate — tiered pricing for MPP endpoints | 60 |
| [**Agent Treaty**](https://github.com/mcevoyinit/tempo-agent-treaty) | Agree — multi-field OTC block trading | 89 |
| **Maestro** | Execute — zero-gas orchestrated settlement | 65 |

**Negotiate → Agree → Execute.** The complete agent economic lifecycle on Tempo.

## Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v  # 65 tests, ~0.6s
```

All tests use real `pytempo` and `pympp` objects — no mocks.

## License

MIT
