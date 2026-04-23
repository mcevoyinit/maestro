"""Session key lifecycle management via AccountKeychain."""

from __future__ import annotations

from pytempo import AccountKeychain, Call, TokenLimit
from pytempo.contracts.account_keychain import KeyRestrictions

from .types import AgentConfig, MaestroConfig


class KeychainManager:
    """Creates, tracks, and revokes scoped session keys for sub-agents."""

    def __init__(self, config: MaestroConfig | None = None):
        self.config = config or MaestroConfig()
        self._agents: dict[str, AgentConfig] = {}

    def register(self, agent: AgentConfig) -> None:
        """Register an agent config for tracking."""
        self._agents[agent.agent_id] = agent

    def get_agent(self, agent_id: str) -> AgentConfig:
        agent = self._agents.get(agent_id)
        if agent is None:
            raise KeyError(f"Agent '{agent_id}' not registered")
        return agent

    @property
    def agents(self) -> dict[str, AgentConfig]:
        return dict(self._agents)

    def build_authorize_call(self, agent: AgentConfig) -> Call:
        """Build a Call that authorizes a session key for this agent."""
        token_limits = tuple(
            TokenLimit(token=token, limit=amount)
            for token, amount in agent.budget_tokens.items()
        ) or None
        restrictions = KeyRestrictions(
            expiry=agent.effective_expiry(),
            limits=token_limits,
        )
        return AccountKeychain.authorize_key(
            key_id=agent.key_id,
            signature_type=self.config.signature_type,
            restrictions=restrictions,
        )

    def build_revoke_call(self, agent: AgentConfig) -> Call:
        """Build a Call that revokes a session key."""
        return AccountKeychain.revoke_key(key_id=agent.key_id)

    def build_update_limit_call(
        self, agent: AgentConfig, token: str, new_limit: int
    ) -> Call:
        """Build a Call that updates a spending limit for an agent's key."""
        return AccountKeychain.update_spending_limit(
            key_id=agent.key_id,
            token=token,
            new_limit=new_limit,
        )

    def build_authorize_all(self) -> list[Call]:
        """Build authorize Calls for all registered agents."""
        return [self.build_authorize_call(a) for a in self._agents.values()]

    def build_revoke_all(self) -> list[Call]:
        """Build revoke Calls for all registered agents."""
        return [self.build_revoke_call(a) for a in self._agents.values()]
