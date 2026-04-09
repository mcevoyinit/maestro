"""Maestro orchestrator — coordinates the full agent lifecycle."""

from __future__ import annotations

import uuid
from typing import Any

from pytempo import TempoTransaction, Call
from mpp.methods.tempo import TempoAccount

from .types import AgentConfig, TaskResult, MaestroConfig
from .keychain import KeychainManager
from .executor import SponsoredExecutor


class Maestro:
    """Zero-gas agent orchestrator for Tempo.

    Lifecycle:
        1. Register sub-agents with scoped budgets
        2. Authorize session keys (one batch tx from master)
        3. Build agent tasks (parallel, sponsored, with memos)
        4. Revoke keys when done

    The master key never leaves the orchestrator.
    Sub-agents hold zero gas — all fees sponsored by master.
    """

    def __init__(
        self,
        master_key: str,
        config: MaestroConfig | None = None,
    ):
        self.config = config or MaestroConfig()
        self.master = TempoAccount.from_key(master_key)
        self.keychain = KeychainManager(self.config)
        self.executor = SponsoredExecutor(self.config)
        self._task_results: list[TaskResult] = []

    @property
    def master_address(self) -> str:
        return self.master.address

    def register_agent(self, agent: AgentConfig) -> None:
        """Register a sub-agent for orchestration."""
        self.keychain.register(agent)

    def build_authorize_tx(self) -> TempoTransaction:
        """Build a single batch tx that authorizes all registered agents' keys.

        This is an atomic operation — all keys are created or none are.
        """
        calls = tuple(self.keychain.build_authorize_all())
        return self.executor.build_batch_tx(calls, nonce_key=0, sponsored=False)

    def build_revoke_tx(self) -> TempoTransaction:
        """Build a single batch tx that revokes all agents' keys."""
        calls = tuple(self.keychain.build_revoke_all())
        return self.executor.build_batch_tx(calls, nonce_key=0, sponsored=False)

    def build_revoke_agent_tx(self, agent_id: str) -> TempoTransaction:
        """Build a tx that revokes a specific agent's key."""
        agent = self.keychain.get_agent(agent_id)
        call = self.keychain.build_revoke_call(agent)
        return self.executor.build_batch_tx((call,), nonce_key=0, sponsored=False)

    def build_agent_task(
        self,
        agent_id: str,
        token_address: str,
        payments: list[dict[str, Any]],
        task_id: str | None = None,
    ) -> tuple[TempoTransaction, str]:
        """Build a sponsored task for a sub-agent.

        Returns (transaction, task_id).
        """
        if not payments:
            raise ValueError("payments must not be empty")
        agent = self.keychain.get_agent(agent_id)
        task_id = task_id or f"task-{uuid.uuid4().hex[:8]}"
        tx = self.executor.build_agent_task_tx(
            agent=agent,
            token_address=token_address,
            payments=payments,
            task_id=task_id,
        )
        return tx, task_id

    def build_parallel_tasks(
        self,
        tasks: list[dict[str, Any]],
        token_address: str,
    ) -> list[tuple[TempoTransaction, str]]:
        """Build multiple agent tasks for parallel execution.

        Each task: {"agent_id": str, "payments": [...], "task_id"?: str}
        Returns list of (transaction, task_id) pairs.
        Each uses the agent's nonce_key for parallel execution.
        """
        results = []
        for task in tasks:
            tx, task_id = self.build_agent_task(
                agent_id=task["agent_id"],
                token_address=token_address,
                payments=task["payments"],
                task_id=task.get("task_id"),
            )
            results.append((tx, task_id))
        return results

    def build_scheduled_task(
        self,
        agent_id: str,
        token_address: str,
        payments: list[dict[str, Any]],
        valid_after: int,
        valid_before: int | None = None,
        task_id: str | None = None,
    ) -> tuple[TempoTransaction, str]:
        """Build a time-locked sponsored task.

        valid_after: earliest block timestamp for execution.
        valid_before: latest block timestamp (optional deadline).
        """
        agent = self.keychain.get_agent(agent_id)
        task_id = task_id or f"sched-{uuid.uuid4().hex[:8]}"

        calls = []
        for payment in payments:
            memo = {
                "task_id": task_id,
                "agent_id": agent_id,
                "scheduled": True,
                **payment.get("memo_extra", {}),
            }
            call = self.executor.build_memo_transfer_call(
                token_address=token_address,
                to=payment["to"],
                amount=payment["amount"],
                memo_data=memo,
            )
            calls.append(call)

        tx = self.executor.build_sponsored_tx(
            agent,
            tuple(calls),
            valid_after=valid_after,
            valid_before=valid_before,
        )
        return tx, task_id

    def record_result(self, result: TaskResult) -> None:
        """Record a task execution result."""
        self._task_results.append(result)

    @property
    def results(self) -> list[TaskResult]:
        return list(self._task_results)
