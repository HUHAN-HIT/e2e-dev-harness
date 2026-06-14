"""Builtin agent-team provider."""
from __future__ import annotations

from e2e_harness.adapters.agent_team import base, registry
from e2e_harness.core import multitrack


class BuiltinAgentTeamProvider:
    name = "builtin"

    def capabilities(self) -> dict:
        return {"provider": self.name, "profiles": [p["name"] for p in registry.load_bundled_profiles()]}

    def plan_phase(self, request: dict) -> dict:
        if request.get("schema") != base.REQUEST_SCHEMA:
            raise ValueError(f"bad agent-team request schema: {request.get('schema')!r}")
        profile_name = request.get("team_profile") or f"default-{request.get('pipeline', 'standard')}"
        profile = registry.load_profile(profile_name, repo_root=request.get("repo_root"))
        phase = request["phase"]
        role = phase["worker_role"]
        role_spec = profile.get("roles", {}).get(role, {})
        phase_spec = profile.get("phases", {}).get(phase["name"], {})
        context_paths = list(request.get("context_paths") or [request.get("run_state_path")])
        produces = list(phase.get("produces") or [])
        max_workers = int((request.get("constraints") or {}).get("max_workers") or role_spec.get("max_workers") or 1)

        if phase_spec.get("strategy") == "evidence-key-fanout":
            workers = self._fanout_workers(phase, role_spec, phase_spec, context_paths, max_workers)
            execution_model = "reviewer-fanout"
        else:
            workers = [self._worker(
                worker_id=f"{phase['name']}-default",
                role=role,
                skill=phase["worker_skill"],
                role_spec=role_spec,
                context_paths=context_paths,
                expected_outputs=produces,
                parallel_group=phase["name"].lower(),
                include_subagent_type=True,
            )]
            execution_model = "single-worker"

        return {
            "schema": base.PLAN_SCHEMA,
            "provider": self.name,
            "profile": profile["name"],
            "phase": phase["name"],
            "execution_model": execution_model,
            "max_workers": max_workers,
            "workers": workers,
            "blocked_parallelism": [],
            "evidence_contract": {
                "required_keys": produces,
                "producer_ids": [worker["id"] for worker in workers],
            },
        }

    def plan_module_fanout(self, request: dict, frontier) -> dict:
        """One worker per ready module phase (B3) — the parallel half of取向②.

        Independent modules surfaced by multitrack.ready_frontier each get their
        own worker, namespaced evidence, and `module:<id>` parallel group. Honours
        depends_on implicitly: a gated module is simply absent from the frontier.
        """
        if request.get("schema") != base.REQUEST_SCHEMA:
            raise ValueError(f"bad agent-team request schema: {request.get('schema')!r}")
        profile_name = request.get("team_profile") or f"default-{request.get('pipeline', 'standard')}"
        profile = registry.load_profile(profile_name, repo_root=request.get("repo_root"))
        roles = profile.get("roles", {})
        context_paths = list(request.get("context_paths") or [request.get("run_state_path")])
        workers = []
        for phase in frontier:
            workers.append(self._worker(
                worker_id=phase.name,
                role=phase.worker_role,
                skill=phase.worker_skill,
                role_spec=roles.get(phase.worker_role, {}),
                context_paths=context_paths,
                expected_outputs=list(phase.produces),
                parallel_group=f"module:{multitrack.module_of(phase.name)}",
                include_subagent_type=True,
            ))
        return {
            "schema": base.PLAN_SCHEMA,
            "provider": self.name,
            "profile": profile["name"],
            "phase": request["phase"]["name"],
            "execution_model": "module-fanout",
            "max_workers": len(workers),
            "workers": workers,
            "blocked_parallelism": [],
            "evidence_contract": {
                "required_keys": [k for w in workers for k in w["expected_outputs"]],
                "producer_ids": [w["id"] for w in workers],
            },
        }

    def _fanout_workers(self, phase: dict, role_spec: dict, phase_spec: dict,
                        context_paths: list[str], max_workers: int) -> list[dict]:
        workers = []
        for entry in phase_spec.get("workers", [])[:max_workers]:
            suffix = entry["id_suffix"]
            workers.append(self._worker(
                worker_id=f"{phase['name']}-{suffix}",
                role=phase["worker_role"],
                skill=phase["worker_skill"],
                role_spec=role_spec,
                context_paths=context_paths,
                expected_outputs=list(entry["expected_outputs"]),
                parallel_group=f"{phase['name'].lower()}:{suffix}",
                include_subagent_type=True,
            ))
        return workers

    def _worker(self, *, worker_id: str, role: str, skill: str, role_spec: dict,
                context_paths: list[str], expected_outputs: list[str],
                parallel_group: str, include_subagent_type: bool) -> dict:
        worker = {
            "id": worker_id,
            "schema": "e2e-dev-harness.worker-packet.v1",
            "role": role,
            "skill": skill,
            "context_paths": list(context_paths),
            "expected_outputs": list(expected_outputs),
            "parallel_group": parallel_group,
            "depends_on": [],
            "context_policy": "fresh",
        }
        declared = str(role_spec.get("runtime_subagent_type", "")).strip()
        if include_subagent_type and declared:
            worker["runtime_subagent_type"] = declared
        return worker
