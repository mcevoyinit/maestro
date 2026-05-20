# Postmortem: silent lane 0 nonce fallback in maestro

Author: Eric McEvoy. Fixed in commit `2c46694` on 2026-04-23.

## What I was trying to build

Maestro lets a master account sponsor sub agents to run concurrent payments on Tempo. Concurrency comes from Tempo's parallel nonce lanes: an agent can stake out a `nonce_key` greater than zero and submit transactions in parallel with another agent on a different `nonce_key`, without nonce collisions. The orchestrator is supposed to make this safe: the caller picks a lane, maestro builds and submits the transaction, and the master signs the fee envelope.

## The bug I shipped

`TxSubmitter.get_nonce()` accepted a `nonce_key` argument, but the implementation just called `eth_getTransactionCount(master, "latest")` and threw the argument away. That call only ever returns the lane 0 nonce. When a caller in a parallel lane (`nonce_key > 0`) submitted a transaction without an explicit `nonce=` arg, `sign_and_send` auto filled the lane 0 nonce into a lane N transaction. Validators reject the resulting envelope, and from the caller's point of view the submit "just failed" with no obvious reason. In the path where lane N happened to be unused, a malformed transaction could land in the wrong slot.

## Why it mattered

The whole point of maestro is parallel safe sponsored execution. Silent lane 0 fallback means the parallel lane premise was a lie under any caller that trusted the API surface. Two sub agents on different lanes both think they got "their" lane nonce, both submit, one wins, one drops, and the orchestrator can not tell which is which after the fact. For a stack that wants to sit in front of a partner running real value through it, fail silent at the nonce layer is exactly the failure shape that becomes a sev 1 when a customer first leans on it.

## Root cause

I optimised for API convenience over fail loud. The docstring on `get_nonce` already said "lane 0 only" but the call site auto filled without enforcing that contract. Docstrings warn humans. Validators do not read docstrings. The contract has to live in code.

The deeper cause: the original function signature took `nonce_key` so I could "add lane support later" without changing callers. That deferred work created a quiet path between the public API and the on chain behaviour that violated the implied invariant.

## Fix, test, commit

Commit `2c46694` on 2026-04-23. The fix is two lines of real logic and a `ValueError`:

```
elif tx.nonce == 0 and tx.nonce_key != 0:
    raise ValueError(
        f"parallel lane (nonce_key={tx.nonce_key}) requires an explicit "
        f"nonce; get_nonce() only returns correct values for lane 0"
    )
```

`tests/test_submitter.py` got 59 lines of new coverage: a parallel lane submit with no explicit nonce now raises, and a parallel lane submit with an explicit nonce still goes through. Total diff: `submitter.py +8/-1`, `test_submitter.py +59/-0`.

## What I changed in engineering posture

Three things stuck.

One. For sponsored execution, fail loud beats fail silent. Convenience defaults are fine on the happy path; outside it, force the caller to pass the ambiguous argument explicitly. Validators do not care about your ergonomics.

Two. If a function signature accepts a parameter the body throws away, you are not deferring work, you are publishing a wrong contract. Either implement the parameter or remove it from the signature.

Three. Tests that pass in lane 0 are not evidence the lane N path works. Test coverage has to follow the dimensions of the actual invariants, not the convenient ones.

## Where I think I can help, and where I should not claim ownership

The applied payments edge of Tempo is where I want to work: sponsored execution, fee payer policy, idempotent settlement, partner facing failure modes, the kind of correctness work where a silent fallback this small turns into a real loss. That is the seat where I have something to add, both from this kind of bug and from the years at R3 and Ethena where the same shape kept showing up at scale.

I am not pitching myself for consensus, virtual machine, or chain core work on Tempo. That is a different discipline and Tempo already has the people for it. The lane I care about is the boundary code that sits in front of the chain and behind the customer.
