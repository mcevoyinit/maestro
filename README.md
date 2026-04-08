# Maestro

Python orchestrator for running gasless agent swarms on [Tempo](https://tempo.xyz). Sub-agents get scoped session keys with spending limits — they can transact without holding any gas tokens. The master pays all fees and can revoke access at any time.

Built on Tempo's 0x76 transaction type ([`pytempo`](https://pypi.org/project/pytempo/), [`pympp`](https://pypi.org/project/pympp/)).

## Live on Testnet

These are real transactions on Tempo Moderato (chain 42431):

```
Simple pathUSD transfer:
  https://explore.moderato.tempo.xyz/tx/0xa431528b5cb7f229ad4a56640ef010c3475ef2f895d1095354a93ed14d6d4c07

Atomic batch — 3 transfers in 1 tx (all-or-nothing):
  https://explore.moderato.tempo.xyz/tx/0xe568ce0568252b9267d811f71f4717d54b1028e428473b1bb7d5926afaaace21

Transfer with SHA-256 memo (on-chain provenance):
  https://explore.moderato.tempo.xyz/tx/0x120aba7bcd52f3cfc60af1fa22e0f7cea8ba74e677e97ac1088bcccf21651281
```

## How It Works

A `Maestro` instance manages one master key and N sub-agents. Each agent gets:
- A **session key** via `AccountKeychain` — time-limited, with per-token spending caps
- Its own **nonce lane** — agents transact in parallel without blocking each other
- **Fee sponsorship** — the master signs the gas envelope, agents hold zero native tokens

All of this is native to Tempo's 0x76 transaction type. No smart contracts to deploy.

```python
from maestro import Maestro, AgentConfig

m = Maestro(master_key="0x...")

m.register_agent(AgentConfig(
    agent_id="researcher",
    key_id="0xAgentAddress",
    nonce_key=1,
    budget_tokens={"0x20C0...0000": 10_000_000},  # $10 pathUSD
))

# authorize all session keys in one atomic batch
auth_tx = m.build_authorize_tx()

# build a task — agent pays recipient with a memo hash
tx, task_id = m.build_agent_task(
    "researcher", "0x20C0...0000",
    payments=[{"to": "0xRecipient", "amount": 1_000_000,
               "memo_extra": {"source": "coingecko", "confidence": 0.92}}],
)

# done — revoke everything
revoke_tx = m.build_revoke_tx()
```

Transactions come back as `TempoTransaction` objects ready to sign and submit. The `TxSubmitter` handles signing, RPC submission, and receipt polling:

```python
from maestro.submitter import TxSubmitter

sub = TxSubmitter(master_account)
receipt = await sub.sign_and_send(tx)
print(receipt.explorer_url)
```

## What Tempo Gives You (That Other Chains Don't)

The reason this works without deploying contracts is that Tempo bakes these into the transaction format:

- `AccountKeychain.authorize_key(key_id, expiry, limits)` — scoped session keys with per-token caps
- `awaiting_fee_payer` — sub-agent builds tx, master pays gas
- `calls=(Call, Call, ...)` — multiple operations in one atomic tx
- `nonce_key` — parallel execution lanes per agent
- `valid_after` / `valid_before` — on-chain scheduling without keepers
- `TIP20.transfer_with_memo(memo)` — 32-byte provenance hash on every payment

On Ethereum you'd need ERC-4337 + a paymaster + a multicall contract + Chainlink keepers to get the same thing. On x402 most of these aren't possible at all.

## Install

```bash
pip install maestro-tempo
```

Or from source:

```bash
git clone https://github.com/mcevoyinit/maestro.git
cd maestro
pip install -e ".[dev]"
pytest tests/ -v  # 69 tests
```

## CLI Demo

```bash
python -m maestro.cli
```

Walks through the full lifecycle: register 3 agents with different budgets → authorize session keys (atomic batch) → parallel tasks across 3 nonce lanes → scheduled task with `valid_after` → revoke keys.

## Testnet Setup

```bash
# fund your wallet (gives 1M of each testnet stablecoin)
curl -X POST https://rpc.moderato.tempo.xyz \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tempo_fundAddress","params":["YOUR_ADDRESS"],"id":1}'
```

| | |
|---|---|
| Chain ID | 42431 |
| RPC | `https://rpc.moderato.tempo.xyz` |
| Explorer | `https://explore.moderato.tempo.xyz` |
| pathUSD | `0x20C0000000000000000000000000000000000000` |
| AccountKeychain | `0xaAAAaaAA00000000000000000000000000000000` |

## Related

- [Parley](https://github.com/mcevoyinit/parley) — tiered pricing for MPP endpoints
- [Agent Treaty](https://github.com/mcevoyinit/tempo-agent-treaty) — multi-field OTC negotiation between agents

## License

MIT
