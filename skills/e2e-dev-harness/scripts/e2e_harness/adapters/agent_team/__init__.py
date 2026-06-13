"""Agent-team planning adapters.

This layer is pure: it expands a lifecycle phase into worker packets, but never
spawns runtimes or mutates run-state.
"""
from e2e_harness.adapters.agent_team.builtin import BuiltinAgentTeamProvider
from e2e_harness.adapters.agent_team.registry import load_profile, load_profiles

__all__ = ["BuiltinAgentTeamProvider", "load_profile", "load_profiles"]
