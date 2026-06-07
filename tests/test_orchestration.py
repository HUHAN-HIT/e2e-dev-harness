"""Orchestration plan, artifact tests, and auto-transition."""
from __future__ import annotations

import io
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import orchestration_plan  # noqa: E402
import scheduling_strategy  # noqa: E402
import agent_roles  # noqa: E402
import auto_transition  # noqa: E402
import phase_guard  # noqa: E402
import run_state  # noqa: E402
import run_summary  # noqa: E402
import session_checkpoint  # noqa: E402
import e2e_dev_harness  # noqa: E402
import install_hooks  # noqa: E402
import harness_stop_guard  # noqa: E402
import agent_instructions  # noqa: E402
import agent_scheduler  # noqa: E402
import artifact_registry  # noqa: E402
import context_pack  # noqa: E402
import coordinator_flow  # noqa: E402
import dispatcher  # noqa: E402
import execution_trace  # noqa: E402
import harness_policy  # noqa: E402
import harness_verify  # noqa: E402
import implementation_gate  # noqa: E402
import memory_capture  # noqa: E402
import reviewer_gate  # noqa: E402
import service_design_gate  # noqa: E402
import task_tier  # noqa: E402


class PhaseFunctionTests(unittest.TestCase):
    """Pin `phase_for_agent` / `depends_on_for_phase` behavior at the registry seam."""

    # Golden phase resolution for the agent names `agent_plan` actually emits,
    # including adversarial service slugs. `code-developer-*-test` MUST stay
    # `implement`: the explicit `code-developer` role prefix outranks an
    # incidental `test` in the service slug. This guards against a future naive
    # "dedup" onto `resolve_role_key` (whose order would wrongly pick tdd-red).
    PHASE_GOLDEN = {
        "requirements-clarifier": "clarify",
        "use-case-designer": "design",
        "service-designer-order-service": "design",
        "service-designer-test": "design",
        "implementation-planner": "plan",
        "test-case-developer": "tdd-red",
        "test-case-developer-order-service": "tdd-red",
        "test-case-developer-code-svc": "tdd-red",
        "code-developer": "implement",
        "code-developer-order-service": "implement",
        "code-developer-notification-test": "implement",
        "code-developer-integration-test": "implement",
        "coverage-reviewer": "completion",
        "design-reviewer": "r1-review",
        "single-reviewer-r1-design": "r1-review",
        "single-reviewer-r2-test": "r2-review",
        "test-reviewer": "r2-review",
        "single-reviewer-r3-implementation": "r3-review",
        "implementation-reviewer": "r3-review",
        "implementation-reviewer-order-service": "r3-review",
        "totally-unknown": "plan",
    }

    def test_phase_for_agent_golden(self) -> None:
        for name, phase in self.PHASE_GOLDEN.items():
            self.assertEqual(phase, orchestration_plan.phase_for_agent(name), name)

    def test_phase_for_agent_keeps_role_prefix_precedence_over_service_slug(self) -> None:
        # The explicit `code-developer` role prefix outranks an incidental
        # `test` in the service slug. `resolve_role_key` now orders
        # `code-developer` before `test` too, so the registry-derived path and
        # `phase_for_agent` agree (both -> "implement") for this adversarial
        # name; the historical divergence (registry -> "tdd-red") is fixed.
        name = "code-developer-notification-test"
        self.assertEqual("implement", orchestration_plan.phase_for_agent(name))
        registry_derived = agent_roles.role_to_phase(agent_roles.resolve_role_key(name))
        self.assertEqual("implement", registry_derived)
        self.assertEqual(registry_derived, orchestration_plan.phase_for_agent(name))

    def test_depends_on_for_phase_delegates_to_registry(self) -> None:
        for phase in list(agent_roles.PHASE_REGISTRY) + ["nonexistent-phase"]:
            self.assertEqual(
                agent_roles.depends_on_for_phase(phase),
                orchestration_plan.depends_on_for_phase(phase),
                phase,
            )

    def test_depends_on_for_phase_unknown_defaults_to_plan(self) -> None:
        self.assertEqual(["plan"], orchestration_plan.depends_on_for_phase("mystery"))

    REVIEWER_PHASES = ("r1-review", "r2-review", "r3-review", "completion")
    GENERAL_PHASES = ("clarify", "design", "plan", "tdd-red", "implement", "unknown-phase")
    ROLE_DEFAULTS = {
        "clarify": "requirements-clarifier",
        "design": "use-case-designer",
        "plan": "implementation-planner",
        "tdd-red": "test-case-developer",
        "implement": "code-developer",
        "r1-review": "semantic-reviewer",
        "r2-review": "semantic-reviewer",
        "r3-review": "semantic-reviewer",
        "completion": "coverage-reviewer",
    }

    def test_runtime_subagent_type_defaults_to_role_declaration_when_env_unset(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != orchestration_plan.REVIEWER_SUBAGENT_TYPE_ENV}
        with patch.dict(os.environ, env, clear=True):
            for phase, expected in self.ROLE_DEFAULTS.items():
                self.assertEqual(expected, orchestration_plan.runtime_subagent_type_for_phase(phase), phase)
            self.assertEqual("general-purpose", orchestration_plan.runtime_subagent_type_for_phase("unknown-phase"))

    def test_runtime_subagent_type_routes_reviewer_phases_when_env_set(self) -> None:
        with patch.dict(os.environ, {orchestration_plan.REVIEWER_SUBAGENT_TYPE_ENV: "code-reviewer"}):
            for phase in self.REVIEWER_PHASES:
                self.assertEqual("code-reviewer", orchestration_plan.runtime_subagent_type_for_phase(phase), phase)
            for phase in self.GENERAL_PHASES:
                expected = self.ROLE_DEFAULTS.get(phase, "general-purpose")
                self.assertEqual(expected, orchestration_plan.runtime_subagent_type_for_phase(phase), phase)

    def test_runtime_subagent_type_honors_per_phase_env_override(self) -> None:
        # A project can route a single phase (e.g. interactive clarify) to a
        # harness-aware subagent without touching the portable default.
        env = {orchestration_plan.subagent_type_env_for_phase("clarify"): "requirements-clarifier-agent"}
        with patch.dict(os.environ, env):
            self.assertEqual(
                "requirements-clarifier-agent",
                orchestration_plan.runtime_subagent_type_for_phase("clarify"),
            )
            # Other phases still follow their role declarations.
            for phase in ("design", "plan", "tdd-red", "implement"):
                self.assertEqual(self.ROLE_DEFAULTS[phase], orchestration_plan.runtime_subagent_type_for_phase(phase), phase)

    def test_per_phase_env_override_beats_reviewer_routing(self) -> None:
        # An explicit per-phase override wins over the reviewer-kind default.
        env = {
            orchestration_plan.REVIEWER_SUBAGENT_TYPE_ENV: "code-reviewer",
            orchestration_plan.subagent_type_env_for_phase("r2-review"): "security-reviewer",
        }
        with patch.dict(os.environ, env):
            self.assertEqual("security-reviewer", orchestration_plan.runtime_subagent_type_for_phase("r2-review"))
            # A reviewer phase without its own override still follows the reviewer env.
            self.assertEqual("code-reviewer", orchestration_plan.runtime_subagent_type_for_phase("r1-review"))


class RoleTemplateFilesTest(unittest.TestCase):
    """`ROLE_TEMPLATE_FILES` derives from the role registry, preserving order."""

    GOLDEN = {
        "requirements-clarifier": "requirements-clarifier.md",
        "use-case-designer": "use-case-designer.md",
        "implementation-planner": "implementation-planner.md",
        "test-case-developer": "test-case-developer.md",
        "code-developer": "code-developer.md",
        "semantic-reviewer": "semantic-reviewer.md",
        "coverage-reviewer": "coverage-reviewer.md",
    }

    def test_role_template_files_match_golden_literal(self) -> None:
        self.assertEqual(self.GOLDEN, dict(orchestration_plan.ROLE_TEMPLATE_FILES))
        self.assertEqual(
            list(self.GOLDEN), list(orchestration_plan.ROLE_TEMPLATE_FILES)
        )

    def test_role_template_files_are_derived_from_registry(self) -> None:
        self.assertEqual(
            {role: f"{role}.md" for role in agent_roles.ROLE_REGISTRY},
            dict(orchestration_plan.ROLE_TEMPLATE_FILES),
        )


def implementation_gate_payload(red_path: Path) -> dict:
    return {
        "phase": "implementation",
        "ready": True,
        "knowledge_graph_status_loaded": True,
        "tdd": {"ready": True, "red_evidence": str(red_path)},
        "semantic_reviews": {"ready": True, "covered_phases": ["design", "test"]},
    }


def write_implemented_state(repo: Path, state_path: Path, state: dict) -> None:
    state["lifecycle"] = "PLANNED"
    run_state.write_state(repo, state_path, state)
    evidence = state_path.parent / "evidence" / "implementation-gate.json"
    red = state_path.parent / "evidence" / "red-test.txt"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    red.write_text("expected failing test\n", encoding="utf-8")
    evidence.write_text(json.dumps(implementation_gate_payload(red)), encoding="utf-8")
    result = run_state.transition_state(
        repo,
        state_path,
        "IMPLEMENTED",
        gate="implementation",
        gate_status="passed",
        evidence=evidence,
    )
    if not result["ready"]:
        raise AssertionError(result["blocked_reasons"])


def write_role_template(repo: Path, path: Path) -> None:
    full = repo / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(
        textwrap.dedent(
            """
            # Role

            ## Role Boundary
            Own exactly one scheduled task.

            ## Allowed Inputs
            Use only the context pack inputs.

            ## Forbidden
            Do not inherit coordinator chat context.

            ## Required Outputs
            Write only scheduled outputs.

            ## Done When
            Return evidence paths for scheduled outputs.
            """
        ).strip(),
        encoding="utf-8",
    )


def write_ready_handoff(repo: Path, path: Path, agent_id: str = "requirements-agent") -> None:
    full = repo / path
    full.parent.mkdir(parents=True, exist_ok=True)
    evidence = full.parents[1] / "evidence" / "requirements-summary.md"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("Requirements clarification evidence.\n", encoding="utf-8")
    evidence_ref = evidence.relative_to(repo).as_posix()
    evidence_hash = hashlib.sha256(evidence.read_bytes()).hexdigest()
    full.write_text(
        textwrap.dedent(
            f"""
            ---
            agent: requirements-clarifier
            agent_id: {agent_id}
            status: ready
            inputs:
              - user request
            outputs:
              - {evidence_ref}
            input_hashes:
              - user-request sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
            output_hashes:
              - {evidence_ref} sha256:{evidence_hash}
            consumed_by:
              - code-developer
            open_questions: None
            ---

            ## Summary
            Requirements are clarified for dispatch.

            ## Facts Used
            User request and service scope were reviewed.

            ## Decisions Made
            The downstream task may use the scheduled context pack.

            ## Open Questions
            None

            ## Downstream Assumptions
            The implementation agent will stay inside scheduled outputs.

            ## Verification Evidence
            Ready marker hash matches this handoff file.
            """
        ).strip(),
        encoding="utf-8",
    )
    marker = full.with_suffix(".ready.json")
    marker.write_text(
        json.dumps(
            {
                "path": full.name,
                "sha256": hashlib.sha256(full.read_bytes()).hexdigest(),
                "producer_agent": agent_id,
                "status": "ready",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def mark_dispatch_running(repo: Path, state_path: Path, task_id: str, agent: str) -> None:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    dispatch = {
        "status": "worker_running",
        "runtime": "codex",
        "current_task_id": task_id,
        "current_agent": agent,
        "worker_handle": f"worker-{task_id}",
        "worker_session": f"worker-session-{task_id}",
    }
    state["dispatch"] = dispatch
    state.setdefault("dispatches", {})[task_id] = dispatch
    run_state.write_state(repo, state_path, state)


def complete_dispatched_task(repo: Path, schedule_path: Path, state_path: Path, task_id: str, agent: str, evidence: list[str]) -> dict:
    mark_dispatch_running(repo, state_path, task_id, agent)
    return dispatcher.dispatch_complete(repo, schedule_path, state_path, task_id, agent, evidence)


class OrchestrationArtifactTests(unittest.TestCase):
    def test_start_creates_controlled_run_design_and_locked_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            args = SimpleNamespace(
                repo=repo,
                feature="Refund MQ",
                request="Publish refund notification after success.",
                design_doc=None,
                agent_run_dir=None,
                run_id="run",
                run_date=None,
                force=False,
                status_file=None,
            )

            code, result = e2e_dev_harness.start(args)
            design = Path(result["design_doc"])
            design_exists = design.exists()
            design_text = design.read_text(encoding="utf-8")
            state = json.loads(Path(result["run_state"]).read_text(encoding="utf-8"))
            lock = json.loads(Path(result["phase_lock"]).read_text(encoding="utf-8"))
            schedule = json.loads(Path(result["agent_schedule"]).read_text(encoding="utf-8"))
            workflow = json.loads(Path(result["workflow_plan"]).read_text(encoding="utf-8"))
            registry = json.loads(Path(result["artifact_registry"]).read_text(encoding="utf-8"))
            guard = phase_guard.validate_action(repo, "Write", [Path("services/refund/src/main/java/RefundService.java")])

        self.assertEqual(0, code)
        self.assertTrue(design_exists)
        self.assertIn("## Restated Intent", design_text)
        self.assertIn("## System Sequence", design_text)
        self.assertIn("sequenceDiagram", design_text)
        self.assertEqual("CREATED", state["lifecycle"])
        self.assertEqual("code-write-locked", lock["state"])
        self.assertEqual("bootstrap", schedule["selected_mode"])
        self.assertEqual("dispatcher-confirmed", schedule["completion_mode"])
        self.assertEqual("coordinator-only-dispatch", schedule["execution_model"])
        self.assertEqual("requirements-clarifier", schedule["tasks"][0]["agent"])
        self.assertEqual("clarify", schedule["tasks"][0]["phase"])
        self.assertTrue(schedule["tasks"][0]["role_template"])
        self.assertEqual("e2e-dev-harness.workflow-plan.v1", workflow["schema"])
        self.assertEqual("auto", workflow["phase_mode"])
        self.assertEqual(result["workflow_plan"], str(Path(result["workflow_plan"])))
        self.assertEqual("standard", state["workflow_profile"])
        self.assertTrue(any(item["type"] == "workflow_plan" for item in registry["artifacts"]))
        self.assertFalse(guard["ready"])

    def test_start_manual_phase_profile_writes_workflow_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            profile = repo / "phase-profile.json"
            profile.write_text(
                json.dumps(
                    {
                        "name": "manual-risk-review",
                        "manual_confirm_phases": ["clarify", "implementation-gate"],
                        "dispatch_policy": {"service_code": "manual-after-IMPLEMENTED"},
                        "custom_checkpoints": [{"id": "risk-owner", "after": "plan"}],
                    }
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                repo=repo,
                feature="Refund MQ",
                request="Publish refund notification after success.",
                design_doc=None,
                agent_run_dir=None,
                run_id="run",
                run_date=None,
                phase_mode="manual",
                workflow_profile="manual-risk-review",
                phase_profile=Path("phase-profile.json"),
                force=False,
                status_file=None,
            )

            code, result = e2e_dev_harness.start(args)
            state = json.loads(Path(result["run_state"]).read_text(encoding="utf-8"))
            workflow = json.loads(Path(result["workflow_plan"]).read_text(encoding="utf-8"))

        self.assertEqual(0, code)
        self.assertEqual("manual", result["phase_mode"])
        self.assertEqual("manual-risk-review", result["workflow_profile"])
        self.assertEqual(["clarify", "implementation-gate"], workflow["manual_confirm_phases"])
        self.assertEqual("manual-after-IMPLEMENTED", workflow["dispatch_policy"]["service_code"])
        self.assertEqual("docs/agent-runs/run/workflow-plan.json", state["workflow_plan"])

    def test_next_reports_clarify_after_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            start_args = SimpleNamespace(
                repo=repo,
                feature="Quote",
                request="Return a quote.",
                design_doc=None,
                agent_run_dir=None,
                run_id="run",
                run_date=None,
                force=False,
                status_file=None,
            )
            _code, start_result = e2e_dev_harness.start(start_args)
            next_args = SimpleNamespace(repo=repo, state=Path(start_result["run_state"]), status_file=None)

            code, result = e2e_dev_harness.next_step(next_args)
            checkpoint_exists = Path(result["session_checkpoint"]["checkpoint"]).exists()

        self.assertEqual(0, code)
        self.assertEqual("CREATED", result["lifecycle"])
        self.assertEqual("clarify", result["next"]["phase"])
        self.assertEqual("e2e-dev-harness.workflow-plan.v1", result["workflow_plan"]["schema"])
        self.assertEqual("auto", result["phase_mode"])
        self.assertEqual("phase-scoped", result["todo_policy"]["mode"])
        self.assertEqual("dispatcher", result["exploration_policy"]["preferred"])
        self.assertTrue(any("dispatch-beat" in item and "--max-workers 1" in item for item in result["required_todo_list"]))
        self.assertTrue(any("requirements-clarifier" in item for item in result["required_todo_list"]))
        self.assertFalse(any("implement" in item.lower() for item in result["required_todo_list"]))
        self.assertTrue(checkpoint_exists)

    def test_session_checkpoint_reports_coordinator_context_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            evidence_dir = state_path.parent / "evidence"
            cli_dir = evidence_dir / "cli-responses"
            events_dir = state_path.parent / "dispatch-events"
            evidence_dir.mkdir(parents=True)
            cli_dir.mkdir(parents=True)
            events_dir.mkdir(parents=True)
            (evidence_dir / "large.md").write_text("x" * 80, encoding="utf-8")
            (cli_dir / "next-1.json").write_text("{}", encoding="utf-8")
            (events_dir / "T01-completed.json").write_text("{}", encoding="utf-8")
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            state["history"] = [{"to": "CLARIFIED"}, {"to": "PLANNED"}]
            run_state.write_state(repo, state_path, state)

            result = session_checkpoint.create(
                repo,
                state_path,
                {"phase": "tdd-red"},
                max_evidence_bytes=40,
                max_phase_events=2,
                max_tool_calls=0,
            )
            checkpoint_data = json.loads(Path(result["checkpoint"]).read_text(encoding="utf-8"))

        budget = result["context_budget"]
        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(budget["handoff_recommended"])
        self.assertIn("evidence_bytes", budget["exceeded_limits"])
        self.assertIn("phase_events", budget["exceeded_limits"])
        self.assertIn("tool_calls", budget["exceeded_limits"])
        self.assertEqual(budget, checkpoint_data["context_budget"])
        self.assertTrue(any("Coordinator context budget exceeded" in warning for warning in result["warnings"]))

    def test_context_budget_estimates_expected_handoffs_from_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state_path.parent.mkdir(parents=True)
            schedule = {
                "tasks": [
                    {"id": f"T{index:02d}", "status": "completed" if index < 4 else "planned"}
                    for index in range(29)
                ]
            }
            (state_path.parent / "agent-schedule.json").write_text(
                json.dumps(schedule), encoding="utf-8"
            )
            state = run_state.build_state(
                "docs/agent-runs/run",
                "multi",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            run_state.write_state(repo, state_path, state)

            budget = session_checkpoint.context_budget(state_path, state)

        # 25 open tasks remain; with a bounded per-session tool-call budget a
        # multi run is expected to need several coordinator handoffs. Surfacing
        # this lets the coordinator treat checkpoint/resume as routine cadence.
        self.assertEqual(budget["planned_tasks"], 25)
        self.assertGreaterEqual(budget["expected_handoffs"], 2)
        self.assertIn("expected_handoffs", budget)

    def test_context_budget_scales_phase_and_tool_limits_with_expected_handoffs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            events_dir = state_path.parent / "dispatch-events"
            events_dir.mkdir(parents=True)
            schedule = {"tasks": [{"id": f"T{index:02d}", "status": "planned"} for index in range(29)]}
            (state_path.parent / "agent-schedule.json").write_text(
                json.dumps(schedule), encoding="utf-8"
            )
            # Cumulative dispatch events above the BASE phase-event ceiling (8) but
            # below the ceiling once it is scaled by expected handoffs for a large run.
            for index in range(12):
                (events_dir / f"T{index:02d}-completed.json").write_text("{}", encoding="utf-8")
            state = run_state.build_state(
                "docs/agent-runs/run",
                "multi",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            run_state.write_state(repo, state_path, state)

            budget = session_checkpoint.context_budget(state_path, state)

        # A 29-task multi run is expected to span >=2 coordinator handoffs, so the
        # chatty phase-event/tool-call ceilings scale with that planned workload
        # instead of forcing a handoff after the first few dispatch events.
        self.assertGreaterEqual(budget["expected_handoffs"], 2)
        self.assertGreater(budget["metrics"]["phase_events"], session_checkpoint.DEFAULT_MAX_PHASE_EVENTS)
        self.assertGreaterEqual(
            budget["limits"]["max_phase_events"],
            session_checkpoint.DEFAULT_MAX_PHASE_EVENTS * 2,
        )
        self.assertNotIn("phase_events", budget["exceeded_limits"])
        self.assertFalse(budget["handoff_recommended"])

    def test_next_surfaces_coordinator_context_budget_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            evidence_dir = state_path.parent / "evidence"
            evidence_dir.mkdir(parents=True)
            (evidence_dir / "large.md").write_text(
                "x" * (session_checkpoint.DEFAULT_MAX_EVIDENCE_BYTES + 1),
                encoding="utf-8",
            )
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            run_state.write_state(repo, state_path, state)

            _code, result = e2e_dev_harness.next_step(SimpleNamespace(repo=repo, state=state_path, status_file=None))

        self.assertTrue(result["coordinator_context_budget"]["handoff_recommended"])
        self.assertIn("evidence_bytes", result["coordinator_context_budget"]["exceeded_limits"])
        self.assertTrue(any("Coordinator context budget exceeded" in warning for warning in result["warnings"]))

    def test_next_includes_global_workflow_overview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single-review",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            run_state.write_state(repo, state_path, state)

            code, result = e2e_dev_harness.next_step(
                SimpleNamespace(repo=repo, state=state_path, status_file=None)
            )

        steps = result["workflow_overview"]["steps"]
        lifecycles = [step["lifecycle"] for step in steps]
        current = [step for step in steps if step["current"]]
        self.assertEqual(0, code)
        self.assertEqual("PLANNED", result["workflow_overview"]["current_lifecycle"])
        self.assertEqual(["CREATED", "CLARIFIED", "SERVICE_DESIGN_REQUIRED", "PLANNED", "RED_READY", "IMPLEMENTED", "REVIEWED", "VERIFIED"], lifecycles)
        self.assertEqual("plan-tdd-red-r2", current[0]["phase"])
        self.assertTrue(all(step["gate_summary"] for step in steps))

    def test_next_created_routes_to_dispatch_bootstrap_clarifier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "bootstrap",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            run_state.write_state(repo, state_path, state)

            code, result = e2e_dev_harness.next_step(
                SimpleNamespace(repo=repo, state=state_path, status_file=None)
            )
            summary = json.loads(Path(result["coordinator_summary_path"]).read_text(encoding="utf-8"))

        self.assertEqual(0, code)
        self.assertEqual("coordinator-only", result["next"]["coordinator_mode"])
        self.assertEqual("dispatch_worker", result["next"]["orchestration_action"])
        self.assertIn("dispatch-beat", result["next"]["dispatch_command"])
        self.assertIn("--max-workers 1", result["next"]["dispatch_command"])
        self.assertEqual("requirements-clarifier", result["next"]["expected_worker"])
        self.assertTrue(any("clarification work locally" in item for item in result["next"]["forbidden_local_actions"]))
        self.assertFalse(any("use dispatch-next in CREATED" in item for item in result["next"]["forbidden_local_actions"]))
        self.assertIn("coordinator_summary_path", result)
        self.assertEqual("CREATED", summary["lifecycle"])
        self.assertIn("next_action", summary)
        self.assertNotIn("workflow_plan", summary)

    def test_next_created_todo_list_keeps_coordinator_out_of_clarifier_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "bootstrap",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            run_state.write_state(repo, state_path, state)

            code, result = e2e_dev_harness.next_step(
                SimpleNamespace(repo=repo, state=state_path, runtime="claude-code", status_file=None)
        )

        joined = "\n".join(result["required_todo_list"])
        self.assertEqual(0, code)
        self.assertIn("dispatch-beat", joined)
        self.assertIn("--max-workers 1", joined)
        self.assertIn("requirements-clarifier", joined)
        self.assertIn("Relay unresolved", joined)
        self.assertNotIn("Run kg_refresh", joined)
        self.assertNotIn("Use GitNexus", joined)
        self.assertNotIn("Fill docs/design", joined)
        self.assertNotIn("clarify --design-doc", joined)

    def test_next_lifecycle_todos_keep_coordinator_on_dispatch_and_gates(self) -> None:
        lifecycles = {
            "CLARIFIED": "dispatch",
            "SERVICE_DESIGN_REQUIRED": "dispatch",
            "PLANNED": "dispatch",
            "IMPLEMENTED": "dispatch",
        }
        forbidden = [
            "Use GitNexus evidence",
            "Fill every service-designs",
            "Capture red-test evidence",
            "Continue TDD red/green",
            "create R1 design review artifacts",
            "write the first red test",
        ]
        for lifecycle, expected in lifecycles.items():
            with self.subTest(lifecycle=lifecycle):
                state = run_state.build_state(
                    "docs/agent-runs/run",
                    "single-review",
                    [],
                    "docs/agent-runs/run/artifact-registry.json",
                    lifecycle,
                )

                result = e2e_dev_harness.next_action_for_lifecycle(lifecycle, state)
                joined = "\n".join(result["required_todo_list"])

                self.assertIn(expected, joined.lower())
                self.assertTrue(any("locally" in item or "coordinator" in item for item in result["forbidden_local_actions"]))
                for phrase in forbidden:
                    self.assertNotIn(phrase, joined)

    def test_phase_guard_created_guidance_keeps_coordinator_out_of_clarifier_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            lock = repo / "docs" / "agent-runs" / "run" / ".phase-lock"
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.write_text("CREATED\n", encoding="utf-8")

            guidance = phase_guard.guidance_for_lifecycle(repo, lock, "CREATED")

        joined = "\n".join(guidance["required_todo_list"])
        self.assertIn("dispatch-beat", joined)
        self.assertIn("--max-workers 1", joined)
        self.assertIn("requirements-clarifier", joined)
        self.assertNotIn("Run kg_refresh", joined)
        self.assertNotIn("Use GitNexus", joined)
        self.assertNotIn("Fill docs/design", joined)
        self.assertNotIn("clarify --design-doc", joined)

    def test_phase_guard_created_guidance_points_to_pending_dispatch_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            lock = run_dir / ".phase-lock"
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.write_text(json.dumps({"lifecycle": "CREATED"}), encoding="utf-8")
            state = run_state.build_state(
                "docs/agent-runs/run",
                "bootstrap",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            state["dispatch"] = {
                "status": "awaiting_runtime_spawn",
                "runtime": "claude-code",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "context_pack": "docs/agent-runs/run/context-packs/T01.json",
                "invocation_path": "docs/agent-runs/run/dispatch-invocations/T01-requirements-clarifier.json",
            }
            run_state.write_state(repo, state_path, state)

            guidance = phase_guard.guidance_for_lifecycle(repo, lock, "CREATED")
            compact = phase_guard.compact_guidance_result(guidance)

        self.assertIn("dispatch-spawn-requests/T01-spawn-request.json", guidance["next_valid_command"])
        self.assertIn("Task ID: T01", guidance["next_valid_command"])
        self.assertIn("Context Pack: docs/agent-runs/run/context-packs/T01.json", guidance["next_valid_command"])
        self.assertIn("awaiting worker acknowledgement", guidance["phase_guidance"])
        self.assertIn("T01", guidance["phase_guidance"])
        self.assertEqual("T01", guidance["pending_dispatch"]["task_id"])
        self.assertEqual("spawn_worker", guidance["pending_dispatch"]["next_gate"])
        self.assertIn("pending_dispatch.spawn_request", compact["guidance_ref"])
        self.assertNotIn("Run e2e_dev_harness.py next", compact["guidance_ref"])

    def test_phase_guard_pending_dispatch_guidance_overrides_any_lifecycle_footer(self) -> None:
        for lifecycle in ("CLARIFIED", "PLANNED", "IMPLEMENTED"):
            for status in ("awaiting_runtime_spawn", "worker_dispatched", "dispatched", "waiting_dispatch"):
                with self.subTest(lifecycle=lifecycle, status=status):
                    with tempfile.TemporaryDirectory() as tmp:
                        repo = Path(tmp)
                        run_dir = repo / "docs" / "agent-runs" / "run"
                        state_path = run_dir / "run-state.json"
                        lock = run_dir / ".phase-lock"
                        lock.parent.mkdir(parents=True, exist_ok=True)
                        lock.write_text(json.dumps({"lifecycle": lifecycle}), encoding="utf-8")
                        state = run_state.build_state(
                            "docs/agent-runs/run",
                            "single-review",
                            [],
                            "docs/agent-runs/run/artifact-registry.json",
                            lifecycle,
                        )
                        state["dispatch"] = {
                            "status": status,
                            "runtime": "claude-code",
                            "current_task_id": "T02",
                            "current_agent": "semantic-reviewer",
                            "context_pack": "docs/agent-runs/run/context-packs/T02.json",
                        }
                        run_state.write_state(repo, state_path, state)

                        guidance = phase_guard.guidance_for_lifecycle(repo, lock, lifecycle)

                    self.assertIn("Task ID: T02", guidance["next_valid_command"])
                    self.assertIn(status, guidance["pending_dispatch"]["status"])
                    self.assertIn("awaiting worker acknowledgement", guidance["phase_guidance"])
                    self.assertIn("T02", guidance["phase_guidance"])

    def test_phase_guard_worker_running_dispatch_does_not_request_spawn_ack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            lock = run_dir / ".phase-lock"
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.write_text(json.dumps({"lifecycle": "PLANNED"}), encoding="utf-8")
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single-review",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "claude-code",
                "current_task_id": "T02",
                "current_agent": "semantic-reviewer",
                "context_pack": "docs/agent-runs/run/context-packs/T02.json",
            }
            run_state.write_state(repo, state_path, state)

            guidance = phase_guard.guidance_for_lifecycle(repo, lock, "PLANNED")

        self.assertNotIn("pending_dispatch", guidance)
        self.assertNotIn("dispatch-spawn-requests", guidance["next_valid_command"])

    def test_phase_guard_pending_dispatch_prefers_dispatches_map_when_primary_is_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            lock = run_dir / ".phase-lock"
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.write_text(json.dumps({"lifecycle": "PLANNED"}), encoding="utf-8")
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single-review",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            state["dispatch"] = {
                "status": "worker_running",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "context_pack": "docs/agent-runs/run/context-packs/T01.json",
            }
            state["dispatches"] = {
                "T01": state["dispatch"],
                "T02": {
                    "status": "waiting_dispatch",
                    "current_task_id": "T02",
                    "current_agent": "semantic-reviewer",
                    "context_pack": "docs/agent-runs/run/context-packs/T02.json",
                },
            }
            run_state.write_state(repo, state_path, state)

            guidance = phase_guard.guidance_for_lifecycle(repo, lock, "PLANNED")

        self.assertEqual("T02", guidance["pending_dispatch"]["task_id"])
        self.assertIn("T02-spawn-request.json", guidance["next_valid_command"])

    def test_phase_guard_guidance_lifecycle_todos_keep_coordinator_on_dispatch_and_gates(self) -> None:
        for lifecycle in ("CLARIFIED", "SERVICE_DESIGN_REQUIRED", "PLANNED", "IMPLEMENTED"):
            with self.subTest(lifecycle=lifecycle):
                with tempfile.TemporaryDirectory() as tmp:
                    repo = Path(tmp)
                    lock = repo / "docs" / "agent-runs" / "run" / ".phase-lock"
                    lock.parent.mkdir(parents=True, exist_ok=True)
                    lock.write_text(lifecycle + "\n", encoding="utf-8")

                    guidance = phase_guard.guidance_for_lifecycle(repo, lock, lifecycle)

                joined = "\n".join(guidance["required_todo_list"])
                self.assertIn("dispatch", joined.lower())
                self.assertNotIn("Fill every service-designs", joined)
                self.assertNotIn("Continue TDD red/green", joined)
                self.assertNotIn("Capture red-test evidence", joined)

    def test_next_and_phase_guard_share_lifecycle_policy(self) -> None:
        for lifecycle in ("CREATED", "CLARIFIED", "SERVICE_DESIGN_REQUIRED", "PLANNED", "RED_READY", "IMPLEMENTED"):
            with self.subTest(lifecycle=lifecycle):
                with tempfile.TemporaryDirectory() as tmp:
                    repo = Path(tmp)
                    lock = repo / "docs" / "agent-runs" / "run" / ".phase-lock"
                    lock.parent.mkdir(parents=True, exist_ok=True)
                    lock.write_text(lifecycle + "\n", encoding="utf-8")
                    state = run_state.build_state(
                        "docs/agent-runs/run",
                        "single-review",
                        [],
                        "docs/agent-runs/run/artifact-registry.json",
                        lifecycle,
                    )

                    action = e2e_dev_harness.next_action_for_lifecycle(lifecycle, state)
                    guidance = phase_guard.guidance_for_lifecycle(repo, lock, lifecycle)

                self.assertEqual(action["required_todo_list"], guidance["required_todo_list"])
                self.assertEqual(action["exploration_policy"], guidance["exploration_policy"])

    def test_next_includes_preflight_summary_and_prioritizes_single_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "bootstrap",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            run_state.write_state(repo, state_path, state)

            _code, result = e2e_dev_harness.next_step(
                SimpleNamespace(repo=repo, state=state_path, status_file=None, runtime="codex")
            )

        self.assertIn("preflight", result)
        self.assertFalse(result["preflight"]["ready"])
        self.assertEqual("runtime_hook", result["preflight"]["blockers"][0]["gate"])
        self.assertEqual("clarification", result["preflight"]["blockers"][1]["gate"])
        self.assertEqual(result["preflight"]["next_single_action"], result["next"]["next_single_action"])

    def test_phase_guard_compact_guidance_keeps_full_policy_out_of_hook_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            lock = run_dir / ".phase-lock"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "bootstrap",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            run_state.write_state(repo, state_path, state)
            lock.write_text(json.dumps({"lifecycle": "CREATED"}), encoding="utf-8")

            result = phase_guard.validate_action(
                repo,
                "TodoWrite",
                [],
                lock_path=lock,
                task_text="Read the codebase locally before dispatching clarification",
                compact_guidance=True,
            )

        self.assertFalse(result["ready"])
        self.assertIn("phase_guidance", result)
        self.assertIn("next_single_action", result)
        self.assertIn("guidance_ref", result)
        self.assertNotIn("required_todo_list", result)
        self.assertNotIn("exploration_policy", result)

    def test_next_planned_routes_tdd_and_r2_through_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single-review",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            run_state.write_state(repo, state_path, state)

            code, result = e2e_dev_harness.next_step(
                SimpleNamespace(repo=repo, state=state_path, status_file=None)
            )

        self.assertEqual(0, code)
        self.assertEqual("coordinator-only", result["next"]["coordinator_mode"])
        self.assertEqual("dispatch_worker", result["next"]["orchestration_action"])
        self.assertIn("dispatch-beat", result["next"]["dispatch_command"])
        self.assertNotIn("Write the first red test", result["next"]["command"])
        self.assertTrue(any("red test locally" in item for item in result["next"]["forbidden_local_actions"]))

    def test_next_planned_includes_execution_packet_for_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single-review",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            run_state.write_state(repo, state_path, state)

            code, result = e2e_dev_harness.next_step(
                SimpleNamespace(repo=repo, state=state_path, runtime="claude-code", status_file=None)
            )
            summary = json.loads(Path(result["coordinator_summary_path"]).read_text(encoding="utf-8"))

        packet = result["execution_packet"]
        self.assertEqual(0, code)
        self.assertEqual("e2e-dev-harness.execution-packet.v1", packet["schema"])
        self.assertEqual("PLANNED", packet["lifecycle"])
        self.assertEqual("tdd-red", packet["phase"])
        self.assertIn("dispatch-beat", packet["primary_command"])
        self.assertTrue(any("red-test evidence" in item for item in packet["required_evidence"]))
        self.assertTrue(any("R2" in item for item in packet["required_evidence"]))
        self.assertTrue(any("production code" in item for item in packet["forbidden_actions"]))
        self.assertTrue(any("RED_READY" in item for item in packet["completion_checks"]))
        self.assertEqual(packet["primary_command"], summary["execution_packet"]["primary_command"])

    def test_next_uses_requested_runtime_for_dispatch_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single-review",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            run_state.write_state(repo, state_path, state)

            code, result = e2e_dev_harness.next_step(
                SimpleNamespace(repo=repo, state=state_path, runtime="claude-code", status_file=None)
            )

        self.assertEqual(0, code)
        self.assertIn("--runtime claude-code", result["next"]["dispatch_command"])
        self.assertNotIn("--runtime codex", result["next"]["dispatch_command"])

    def test_next_red_ready_routes_only_to_implementation_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single-review",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "RED_READY",
            )
            run_state.write_state(repo, state_path, state)

            code, result = e2e_dev_harness.next_step(
                SimpleNamespace(repo=repo, state=state_path, status_file=None)
            )

        self.assertEqual(0, code)
        self.assertEqual("coordinator-only", result["next"]["coordinator_mode"])
        self.assertEqual("run_gate", result["next"]["orchestration_action"])
        self.assertIn("gate", result["next"]["dispatch_command"])
        self.assertTrue(any("worker" in item.lower() for item in result["next"]["forbidden_local_actions"]))

    def test_next_red_ready_execution_packet_only_opens_implementation_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single-review",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "RED_READY",
            )
            run_state.write_state(repo, state_path, state)

            code, result = e2e_dev_harness.next_step(
                SimpleNamespace(repo=repo, state=state_path, runtime="claude-code", status_file=None)
            )

        packet = result["execution_packet"]
        self.assertEqual(0, code)
        self.assertEqual("implementation-gate", packet["phase"])
        self.assertEqual("implementation", packet["next_gate"])
        self.assertIn("--phase implementation", packet["primary_command"])
        self.assertTrue(any("implementation gate" in item for item in packet["required_evidence"]))
        self.assertTrue(any("production code" in item for item in packet["forbidden_actions"]))
        self.assertTrue(any("IMPLEMENTED" in item for item in packet["completion_checks"]))

    def test_next_waiting_dispatch_execution_packet_requires_worker_ack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single-review",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "WAITING_DISPATCH",
            )
            run_state.write_state(repo, state_path, state)

            code, result = e2e_dev_harness.next_step(
                SimpleNamespace(repo=repo, state=state_path, runtime="claude-code", status_file=None)
            )

        packet = result["execution_packet"]
        self.assertEqual(0, code)
        self.assertEqual("waiting-dispatch", packet["phase"])
        self.assertEqual("dispatch_ack", packet["next_gate"])
        self.assertIn("dispatch-ack", packet["primary_command"])
        self.assertTrue(any("worker acknowledgement" in item for item in packet["required_evidence"]))
        self.assertTrue(any("complete the task before" in item for item in packet["forbidden_actions"]))
        self.assertTrue(any("worker_running" in item for item in packet["completion_checks"]))

    def test_next_active_dispatch_execution_packet_requires_worker_ack_without_waiting_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single-review",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            state["dispatch"] = {
                "status": "waiting_dispatch",
                "runtime": "manual",
                "current_task_id": "T01",
                "current_agent": "test-case-developer",
            }
            state["dispatches"] = {"T01": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)

            code, result = e2e_dev_harness.next_step(
                SimpleNamespace(repo=repo, state=state_path, runtime="claude-code", status_file=None)
            )

        packet = result["execution_packet"]
        self.assertEqual(0, code)
        self.assertEqual("PLANNED", result["lifecycle"])
        self.assertEqual("waiting-dispatch", packet["phase"])
        self.assertEqual("dispatch_ack", packet["next_gate"])
        self.assertIn("dispatch-ack", packet["primary_command"])

    def test_next_rework_required_execution_packet_routes_to_rework_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single-review",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "REWORK_REQUIRED",
            )
            run_state.write_state(repo, state_path, state)

            code, result = e2e_dev_harness.next_step(
                SimpleNamespace(repo=repo, state=state_path, runtime="claude-code", status_file=None)
            )

        packet = result["execution_packet"]
        self.assertEqual(0, code)
        self.assertEqual("rework", packet["phase"])
        self.assertEqual("rework", packet["next_gate"])
        self.assertTrue(any("return_phase" in item for item in packet["required_actions"]))
        self.assertTrue(any("rework item" in item for item in packet["required_evidence"]))
        self.assertTrue(any("unrouted" in item for item in packet["forbidden_actions"]))
        self.assertTrue(any("verified" in item for item in packet["completion_checks"]))

    def test_phase_guard_requires_fresh_session_checkpoint_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            write_implemented_state(repo, state_path, state)

            blocked = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/main/java/PaymentService.java")],
                run_dir=Path("docs/agent-runs/run"),
                require_session_checkpoint=True,
            )
            checkpoint = session_checkpoint.create(repo, state_path, {"phase": "implement-or-complete"})
            checkpointed_state = json.loads(state_path.read_text(encoding="utf-8"))
            checkpointed_state["dispatches"] = {
                "T07": {
                    "status": "worker_running",
                    "current_task_id": "T07",
                    "current_agent": "code-developer",
                    "worker_handle": "code-worker-1",
                }
            }
            checkpointed_state["dispatch"] = checkpointed_state["dispatches"]["T07"]
            run_state.write_state(repo, state_path, checkpointed_state)
            checkpoint = session_checkpoint.create(repo, state_path, {"phase": "implement-or-complete"})
            allowed = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/main/java/PaymentService.java")],
                run_dir=Path("docs/agent-runs/run"),
                require_session_checkpoint=True,
            )

        self.assertFalse(blocked["ready"])
        self.assertTrue(any("Session resume checkpoint" in reason for reason in blocked["blocked_reasons"]))
        self.assertTrue(checkpoint["ready"], checkpoint["blocked_reasons"])
        self.assertTrue(allowed["ready"], allowed["blocked_reasons"])

    def test_phase_guard_blocks_code_todo_list_before_clarify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "TodoWrite",
                [],
                run_dir=Path("docs/agent-runs/run"),
                task_text="填充 URCS 设计文档并完成 clarify 门禁 完成 jeepay-core 模块开发（实体+常量+模型） 完成 jeepay-service 模块开发",
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Todo list blocked" in reason for reason in result["blocked_reasons"]))
        self.assertIn("required_todo_list", result)

    def test_phase_guard_allows_phase_scoped_todo_list_before_clarify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "TodoWrite",
                [],
                run_dir=Path("docs/agent-runs/run"),
                task_text="Run dispatch-next for requirements-clarifier, then relay worker Restated Intent and Open Questions.",
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_phase_guard_allows_clarifier_dispatch_task_when_prompt_mentions_code_keyword(self) -> None:
        # Regression: the requirements-clarifier is the FIRST task of every run
        # (lifecycle CREATED). Its dispatch prompt naturally describes the
        # feature to clarify and can contain a code keyword (e.g. Chinese
        # "实现"). The structured schedule role (role_group=design) is
        # authoritative and must NOT be overridden by a CODE_TASK_RE keyword
        # match that routes the Task down the IMPLEMENTED-gated code-agent path,
        # which can never pass at CREATED -> first-step deadlock.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "bootstrap",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            state["dispatch"] = {
                "status": "awaiting_runtime_spawn",
                "runtime": "claude-code",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "context_pack": "docs/agent-runs/run/context-packs/T01.json",
            }
            state["dispatches"] = {"T01": state["dispatch"]}
            run_state.write_state(repo, state_path, state)
            run_state.write_phase_lock(repo, state_path, state)
            schedule_path = run_dir / "agent-schedule.json"
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "selected_mode": "bootstrap",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "role_group": "design",
                                "dispatch_contract": "fresh-subagent",
                                "runtime_subagent_type": "requirements-clarifier",
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            pack_path = run_dir / "context-packs" / "T01.json"
            pack_path.parent.mkdir(parents=True, exist_ok=True)
            pack_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.context-pack.v1",
                        "task": {"id": "T01", "agent": "requirements-clarifier"},
                        "schedule": "docs/agent-runs/run/agent-schedule.json",
                    }
                ),
                encoding="utf-8",
            )

            result = phase_guard.validate_action(
                repo,
                "Task",
                [],
                run_dir=Path("docs/agent-runs/run"),
                task_text=(
                    "Task ID: T01\nAgent: requirements-clarifier\nPhase: clarify\n"
                    "Context Pack: docs/agent-runs/run/context-packs/T01.json\n"
                    "澄清结算需求：明确要实现的结算口径与验收标准。"
                ),
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_phase_guard_blocks_clarification_todo_without_user_interaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "TodoWrite",
                [],
                run_dir=Path("docs/agent-runs/run"),
                task_text="Fill design doc and run clarify gate.",
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("dispatch-only" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(result["clarification_interaction"]["interaction_required"])
        requests = result["clarification_interaction"]["ask_user_requests"]
        self.assertTrue(any(request["id"] == "confirm_restated_intent" for request in requests))
        self.assertTrue(any(request["id"] == "resolve_open_questions" for request in requests))

    def test_next_created_exposes_clarification_interaction_contract(self) -> None:
        result = e2e_dev_harness.next_action_for_lifecycle("CREATED", {})

        self.assertTrue(result["clarification_interaction"]["interaction_required"])
        self.assertTrue(result["clarification_interaction"]["must_wait_for_user_answer"])
        self.assertTrue(any("Restated Intent" in item for item in result["required_todo_list"]))
        self.assertTrue(any("requirements-clarifier" in item for item in result["required_todo_list"]))
        requests = result["clarification_interaction"]["ask_user_requests"]
        self.assertTrue(any(request["id"] == "confirm_restated_intent" for request in requests))
        intent_request = next(request for request in requests if request["id"] == "confirm_restated_intent")
        self.assertTrue(any("Confirm" in option["label"] for option in intent_request["options"]))
        self.assertTrue(any("Revise" in option["label"] for option in intent_request["options"]))
        runtime_action = result["clarification_interaction"]["runtime_action"]
        self.assertEqual("request_user_input", runtime_action["tool"])
        self.assertEqual("codex.request_user_input.v1", runtime_action["schema"])
        self.assertEqual(requests, runtime_action["source_requests"])
        self.assertTrue(
            any(question["id"] == "confirm_restated_intent" for question in runtime_action["arguments"]["questions"])
        )
        self.assertFalse(
            any("provenance_required" in question for question in runtime_action["arguments"]["questions"])
        )

    def test_clarify_blocked_returns_questions_to_ask_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True, exist_ok=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Goal
                    - Add payment risk control.

                    ## Scope
                    - Affected services/modules: payment-service
                    - Non-goals: reporting

                    ## Use Cases
                    - UC-1: reject risky payment.

                    ## Acceptance Criteria
                    - AC-1: risky payments are rejected.

                    ## Test Design
                    - First red test: PaymentRiskTest.rejectsRiskyPayment
                    - Verification command: mvn -pl payment-service test

                    ## Open Questions
                    - Which risk score threshold should block payment?
                    """
                ).strip(),
                encoding="utf-8",
            )

            code, result = e2e_dev_harness.clarify(
                SimpleNamespace(repo=repo, design_doc=Path("docs/design/feature.md"), run_state=None, require_intent=False, status_file=None)
            )

        self.assertEqual(2, code)
        self.assertTrue(result["interaction_required"])
        self.assertTrue(any("risk score threshold" in item for item in result["questions_to_ask_user"]))
        self.assertEqual("codex.request_user_input.v1", result["interaction_contract"]["ask_user_schema"])
        requests = result["interaction_contract"]["ask_user_requests"]
        self.assertTrue(any("risk score threshold" in request["question"] for request in requests))
        threshold_request = next(request for request in requests if "risk score threshold" in request["question"])
        self.assertTrue(any("Answer now" in option["label"] for option in threshold_request["options"]))
        self.assertTrue(any("Defer" in option["label"] for option in threshold_request["options"]))
        runtime_action = result["interaction_contract"]["runtime_action"]
        self.assertEqual("request_user_input", runtime_action["tool"])
        self.assertTrue(
            any("risk score threshold" in question["question"] for question in runtime_action["arguments"]["questions"])
        )
        self.assertFalse(
            any("provenance_required" in question for question in runtime_action["arguments"]["questions"])
        )

    def test_clarify_defaults_to_user_confirmation_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True, exist_ok=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Restated Intent
                    - The user wants payment risk control.

                    ## Goal
                    - Add payment risk control.

                    ## Scope
                    - Affected services/modules: payment-service
                    - Non-goals: reporting

                    ## Use Cases
                    - UC-1: reject risky payment.

                    ## Acceptance Criteria
                    - AC-1: risky payments are rejected.

                    ## Test Design
                    - First red test: PaymentRiskTest.rejectsRiskyPayment

                    ## Open Questions
                    - None
                    """
                ).strip(),
                encoding="utf-8",
            )

            code, result = e2e_dev_harness.clarify(
                SimpleNamespace(repo=repo, design_doc=Path("docs/design/feature.md"), run_state=None, status_file=None)
            )

        self.assertEqual(2, code)
        self.assertTrue(result["user_confirmation_required"])
        self.assertTrue(any("confirmed-by: user" in item for item in result["questions_to_ask_user"]))

    def test_stop_guidance_created_waits_for_user_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)

            result = harness_stop_guard.evaluate(repo, state_path)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertFalse(result["guidance"]["must_continue"])
        self.assertIn("Ask the user", result["guidance"]["agent_instruction"])
        self.assertNotIn("Do not ask the user", result["guidance"]["agent_instruction"])

    def test_phase_guard_blocks_exploration_todo_without_gitnexus_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "TodoWrite",
                [],
                run_dir=Path("docs/agent-runs/run"),
                task_text="Analyze affected modules and dependency impact with rg/Read before filling the design.",
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("dispatch-only" in reason for reason in result["blocked_reasons"]))
        self.assertEqual("dispatcher", result["exploration_policy"]["preferred"])

    def test_phase_guard_blocks_exploration_todo_with_gitnexus_first_in_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "TodoWrite",
                [],
                run_dir=Path("docs/agent-runs/run"),
                task_text="Run GitNexus query/impact for affected modules, then use rg only for missing seed discovery.",
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("dispatch-only" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_blocks_stale_session_checkpoint_after_state_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)
            checkpoint = session_checkpoint.create(repo, state_path, {"phase": "tdd-red"})
            write_implemented_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/main/java/PaymentService.java")],
                run_dir=Path("docs/agent-runs/run"),
                require_session_checkpoint=True,
            )

        self.assertTrue(checkpoint["ready"], checkpoint["blocked_reasons"])
        self.assertFalse(result["ready"])
        self.assertTrue(any("stale" in reason.lower() for reason in result["blocked_reasons"]))

    def test_next_blocks_when_claude_hook_is_detected_but_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".claude").mkdir()
            start_args = SimpleNamespace(
                repo=repo,
                feature="Quote",
                request="Return a quote.",
                design_doc=None,
                agent_run_dir=None,
                run_id="run",
                run_date=None,
                force=False,
                status_file=None,
            )
            _code, start_result = e2e_dev_harness.start(start_args)
            next_args = SimpleNamespace(repo=repo, state=Path(start_result["run_state"]), status_file=None)

            code, result = e2e_dev_harness.next_step(next_args)

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])
        self.assertEqual("claude", result["hook_status"]["runtime"])
        self.assertTrue(any("Runtime hook is not ready" in reason for reason in result["blocked_reasons"]))

    def test_runtime_hook_status_accepts_ready_opencode_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            install_hooks.install(repo, "opencode")

            result = e2e_dev_harness.runtime_hook_status(repo)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("opencode", result["runtime"])

    def test_discovery_mode_has_no_agent_plan(self) -> None:
        artifacts = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        agents = orchestration_plan.agent_plan("discovery", artifacts, [])

        self.assertEqual([], agents)

    def test_single_service_plan_splits_design_test_code_and_review_roles(self) -> None:
        artifacts = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        agents = orchestration_plan.agent_plan("single", artifacts, [])
        names = [agent["name"] for agent in agents]
        planner = next(agent for agent in agents if agent["name"] == "implementation-planner")
        code = next(agent for agent in agents if agent["name"] == "code-developer")

        self.assertNotIn("single-agent", names)
        self.assertIn("requirements-clarifier", names)
        self.assertIn("use-case-designer", names)
        self.assertIn("implementation-planner", names)
        self.assertIn("test-case-developer", names)
        self.assertIn("code-developer", names)
        self.assertIn("design-reviewer", names)
        self.assertIn("test-reviewer", names)
        self.assertIn("implementation-reviewer", names)
        self.assertIn(artifacts["exec_plan"], planner["outputs"])
        self.assertIn(artifacts["implementation_plan"], code["inputs"])
        self.assertNotIn(artifacts["design_review"], code["outputs"])
        self.assertNotIn(artifacts["implementation_review"], code["outputs"])
        schedule = orchestration_plan.agent_schedule("single", [], agents)
        self.assertTrue(schedule["require_role_templates"])
        self.assertEqual("dispatcher-confirmed", schedule["completion_mode"])
        self.assertEqual("coordinator-only-dispatch", schedule["execution_model"])
        for task in schedule["tasks"]:
            self.assertIn("agent-roles/", task["role_template"])
        by_agent = {task["agent"]: task for task in schedule["tasks"]}
        self.assertEqual("plan", by_agent["implementation-planner"]["phase"])
        self.assertEqual("planning", by_agent["implementation-planner"]["role_group"])
        self.assertEqual(["r1-review"], by_agent["implementation-planner"]["depends_on_phases"])
        self.assertEqual(
            ["design", "r1-review", "plan"],
            by_agent["test-case-developer"]["depends_on_phases"],
        )

    def test_schedule_marks_planner_and_reviewers_for_fresh_runtime_dispatch(self) -> None:
        artifacts = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        agents = orchestration_plan.agent_plan("single-review", artifacts, [])
        schedule = orchestration_plan.agent_schedule("single-review", [], agents)
        by_phase = {task["phase"]: task for task in schedule["tasks"] if task["phase"] in {"plan", "r1-review", "r2-review", "r3-review"}}

        self.assertEqual({"plan", "r1-review", "r2-review", "r3-review"}, set(by_phase))
        for task in by_phase.values():
            self.assertTrue(task["requires_runtime_dispatch"])
            self.assertEqual("fresh-subagent", task["dispatch_contract"])
            self.assertEqual(PhaseFunctionTests.ROLE_DEFAULTS[task["phase"]], task["runtime_subagent_type"])

    def test_select_services_discovery_does_not_use_all_candidates(self) -> None:
        facts = {"service_candidates": ["services/order-service", "services/payment-service", "services/catalog-service"]}

        selected, resolved_scope = orchestration_plan.select_services(
            facts,
            requested_services=None,
            requested_paths=None,
            service_scope="auto",
        )

        self.assertEqual([], selected)
        self.assertEqual("discovery", resolved_scope)

    def test_select_services_affected_uses_only_requested_service(self) -> None:
        facts = {"service_candidates": ["services/order-service", "services/payment-service", "services/catalog-service"]}

        selected, resolved_scope = orchestration_plan.select_services(
            facts,
            requested_services=["payment-service"],
            requested_paths=None,
            service_scope="auto",
        )

        self.assertEqual(["services/payment-service"], selected)
        self.assertEqual("affected", resolved_scope)

    def test_design_affected_modules_select_root_maven_modules(self) -> None:
        facts = {"service_candidates": ["jeepay-core", "jeepay-service", "jeepay-payment"]}
        design_text = textwrap.dedent(
            """
            # VNPay

            ## Affected services/modules
            - jeepay-core: constants and params
            - jeepay-service: channel config service
            - jeepay-payment: payment, notice, refund services
            """
        ).strip()

        selected = orchestration_plan.services_from_design(design_text, facts)

        self.assertEqual(["jeepay-core", "jeepay-service", "jeepay-payment"], selected)

    @staticmethod
    def _risk_partition_design() -> str:
        return textwrap.dedent(
            """
            # VNPay

            ## Affected services/modules
            - jeepay-core
            - jeepay-service
            - jeepay-payment

            ### jeepay-core
            jeepay-core adds VNPay constants and params.

            ### jeepay-service
            jeepay-service registers the VNPay channel config.

            ### jeepay-payment
            jeepay-payment adds payment and refund services with notify callback handling.
            """
        ).strip()

    def test_service_design_risk_flags_only_risky_section_bodies(self) -> None:
        design_text = self._risk_partition_design()

        self.assertTrue(orchestration_plan.service_design_risk("jeepay-payment", design_text))
        self.assertFalse(orchestration_plan.service_design_risk("jeepay-core", design_text))
        self.assertFalse(orchestration_plan.service_design_risk("jeepay-service", design_text))

    def test_service_design_risk_uses_expanded_financial_keywords(self) -> None:
        design_text = textwrap.dedent(
            """
            # Settlement

            ### jeepay-settle
            jeepay-settle handles settlement payout and withdraw flows.
            """
        ).strip()

        self.assertTrue(orchestration_plan.service_design_risk("jeepay-settle", design_text))

    def test_partition_services_keeps_only_risky_service_as_slice(self) -> None:
        design_text = self._risk_partition_design()
        facts = {"service_candidates": ["jeepay-core", "jeepay-service", "jeepay-payment"]}

        slice_services, merged_services = orchestration_plan.partition_services(
            ["jeepay-core", "jeepay-service", "jeepay-payment"],
            explicit_services=None,
            explicit_paths=None,
            dependency_services=[],
            design_text=design_text,
            facts=facts,
        )

        self.assertEqual(["jeepay-payment"], slice_services)
        self.assertEqual(["jeepay-core", "jeepay-service"], merged_services)

    def test_partition_services_explicit_service_forces_slice(self) -> None:
        design_text = self._risk_partition_design()
        facts = {"service_candidates": ["jeepay-core", "jeepay-service", "jeepay-payment"]}

        slice_services, merged_services = orchestration_plan.partition_services(
            ["jeepay-core", "jeepay-service", "jeepay-payment"],
            explicit_services=["jeepay-core"],
            explicit_paths=None,
            dependency_services=[],
            design_text=design_text,
            facts=facts,
        )

        self.assertEqual(["jeepay-core", "jeepay-payment"], slice_services)
        self.assertEqual(["jeepay-service"], merged_services)

    def test_partition_services_explicit_path_and_dependency_force_slice(self) -> None:
        design_text = self._risk_partition_design()
        facts = {"service_candidates": ["jeepay-core", "jeepay-service", "jeepay-payment"]}

        slice_services, merged_services = orchestration_plan.partition_services(
            ["jeepay-core", "jeepay-service", "jeepay-payment"],
            explicit_services=None,
            explicit_paths=["jeepay-core/src/main/java/Constants.java"],
            dependency_services=["jeepay-service"],
            design_text=design_text,
            facts=facts,
        )

        self.assertEqual(["jeepay-core", "jeepay-service", "jeepay-payment"], slice_services)
        self.assertEqual([], merged_services)

    def test_plan_service_layout_merges_low_risk_services(self) -> None:
        design_text = self._risk_partition_design()
        facts = {"service_candidates": ["jeepay-core", "jeepay-service", "jeepay-payment"]}

        layout = orchestration_plan.plan_service_layout(
            ["jeepay-core", "jeepay-service", "jeepay-payment"],
            explicit_services=None,
            explicit_paths=None,
            dependency_services=[],
            design_text=design_text,
            facts=facts,
        )

        self.assertEqual(["jeepay-payment"], layout["slice_services"])
        self.assertEqual(["jeepay-core", "jeepay-service"], layout["merged_services"])
        self.assertEqual("merged-modules", layout["merged_id"])
        self.assertEqual(["jeepay-payment", "merged-modules"], layout["artifact_services"])
        self.assertEqual(["jeepay-core/", "jeepay-service/"], layout["shared_edit_scopes"])
        self.assertEqual(
            {"jeepay-core/": "merged-modules", "jeepay-service/": "merged-modules"},
            layout["shared_edit_scope_owners"],
        )

    def test_plan_service_layout_without_merge_keeps_services(self) -> None:
        layout = orchestration_plan.plan_service_layout(
            ["jeepay-core", "jeepay-payment"],
            explicit_services=["jeepay-core", "jeepay-payment"],
            explicit_paths=None,
            dependency_services=[],
            design_text="",
            facts={"service_candidates": ["jeepay-core", "jeepay-payment"]},
        )

        self.assertEqual(["jeepay-core", "jeepay-payment"], layout["slice_services"])
        self.assertEqual([], layout["merged_services"])
        self.assertEqual("", layout["merged_id"])
        self.assertEqual(["jeepay-core", "jeepay-payment"], layout["artifact_services"])
        self.assertEqual([], layout["shared_edit_scopes"])

    def test_plan_service_layout_single_service_never_merges(self) -> None:
        layout = orchestration_plan.plan_service_layout(
            ["jeepay-core"],
            explicit_services=None,
            explicit_paths=None,
            dependency_services=[],
            design_text="",
            facts={"service_candidates": ["jeepay-core"]},
        )

        self.assertEqual(["jeepay-core"], layout["slice_services"])
        self.assertEqual([], layout["merged_services"])
        self.assertEqual(["jeepay-core"], layout["artifact_services"])
        self.assertEqual([], layout["shared_edit_scopes"])

    @staticmethod
    def _vnpay_risk_tiered_design() -> str:
        return textwrap.dedent(
            """
            # VNPay

            ## Goal
            - Add VNPay channel.

            ## Affected services/modules
            - jeepay-core
            - jeepay-service
            - jeepay-payment

            ### jeepay-core
            jeepay-core adds VNPay constants and params.

            ### jeepay-service
            jeepay-service registers the VNPay channel config.

            ### jeepay-payment
            jeepay-payment adds payment and refund services with notify callback handling.

            ## Use Cases
            - Merchant creates a VNPay QR payment.

            ## Acceptance Criteria
            - AC-1 VNPay order can be created.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()

    def test_orchestration_status_merges_low_risk_services_into_one_slice(self) -> None:
        facts = {
            "service_candidates": ["jeepay-core", "jeepay-service", "jeepay-payment"],
            "multi_service": True,
            "design_docs_or_media_count": 0,
            "spring_entrypoints": [],
        }
        design_text = self._vnpay_risk_tiered_design()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "vnpay.md"
            design.parent.mkdir(parents=True)
            design.write_text(design_text, encoding="utf-8")

            result = e2e_dev_harness.orchestration_status(
                repo,
                "auto",
                design,
                run_date="2026-05-23",
                service_scope="auto",
                facts=facts,
            )

        # selected_services stays full so reporting and require_handoffs see every affected module.
        self.assertEqual(
            ["jeepay-core", "jeepay-service", "jeepay-payment"], result["selected_services"]
        )
        # Only the risky payment module earns its own slice; the rest collapse into one merged slice.
        self.assertEqual(["jeepay-payment"], result["slice_services"])
        self.assertEqual(["jeepay-core", "jeepay-service"], result["merged_services"])
        self.assertEqual(["jeepay-core/", "jeepay-service/"], result["shared_edit_scopes"])
        self.assertEqual(
            {"jeepay-core/": "merged-modules", "jeepay-service/": "merged-modules"},
            result["shared_edit_scope_owners"],
        )
        service_plans = result["handoff_artifacts"]["service_plans"]
        self.assertIn("jeepay-payment", service_plans)
        self.assertIn("merged-modules", service_plans)
        self.assertNotIn("jeepay-core", service_plans)
        self.assertNotIn("jeepay-service", service_plans)
        agent_names = [agent["name"] for agent in result["agents"]]
        self.assertIn("code-developer-jeepay-payment", agent_names)
        self.assertIn("code-developer-merged-modules", agent_names)
        self.assertNotIn("code-developer-jeepay-service", agent_names)
        self.assertNotIn("code-developer-jeepay-core", agent_names)
        # Slice count (one per service-designer agent) drops below the full service count.
        designer_count = len([name for name in agent_names if name.startswith("service-designer-")])
        self.assertEqual(2, designer_count)
        self.assertLess(designer_count, len(result["selected_services"]))
        self.assertTrue(result["multi_agent_decision"]["use_multi_agent"])

    def test_plan_archive_merges_low_risk_services_into_shared_slice(self) -> None:
        design_text = self._vnpay_risk_tiered_design()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            repo.joinpath("pom.xml").write_text(
                textwrap.dedent(
                    """
                    <project xmlns="http://maven.apache.org/POM/4.0.0">
                      <modelVersion>4.0.0</modelVersion>
                      <modules>
                        <module>jeepay-core</module>
                        <module>jeepay-service</module>
                        <module>jeepay-payment</module>
                      </modules>
                    </project>
                    """
                ).strip(),
                encoding="utf-8",
            )
            for module in ("jeepay-core", "jeepay-service", "jeepay-payment"):
                module_dir = repo / module
                (module_dir / "src" / "main" / "java").mkdir(parents=True)
                (module_dir / "pom.xml").write_text("<project />", encoding="utf-8")
            design = repo / "docs" / "design" / "vnpay.md"
            design.parent.mkdir(parents=True)
            design.write_text(design_text, encoding="utf-8")
            args = SimpleNamespace(
                repo=repo,
                mode="auto",
                design_doc=design,
                agent_run_dir=None,
                run_date="2026-05-23",
                service_scope="auto",
                service=None,
                path=None,
                dependency_report=None,
                create_archive=True,
                write_exec_plan=None,
                status_file=None,
            )

            code, result = e2e_dev_harness.plan(args)

            self.assertEqual(0, code)
            self.assertEqual(
                ["jeepay-core", "jeepay-payment", "jeepay-service"],
                sorted(result["selected_services"]),
            )
            self.assertEqual(["jeepay-payment"], result["slice_services"])
            self.assertEqual(["jeepay-core/", "jeepay-service/"], result["shared_edit_scopes"])
            service_plans = result["handoff_artifacts"]["service_plans"]
            self.assertIn("merged-modules", service_plans)
            self.assertIn("jeepay-payment", service_plans)
            self.assertNotIn("jeepay-core", service_plans)
            self.assertNotIn("jeepay-service", service_plans)

            # Run-state routes the slice through `services` and the merged modules through shared scopes.
            state = json.loads(
                (repo / result["handoff_artifacts"]["run_state"]).read_text(encoding="utf-8")
            )
            self.assertEqual("SERVICE_DESIGN_REQUIRED", state["lifecycle"])
            self.assertEqual(["jeepay-payment"], state["services"])
            self.assertEqual(["jeepay-core/", "jeepay-service/"], state["shared_edit_scopes"])
            self.assertEqual(
                {"jeepay-core/": "merged-modules", "jeepay-service/": "merged-modules"},
                state["shared_edit_scope_owners"],
            )

            # Merged slice still has its own service-design + forced R2/R3 review requests on disk.
            merged_paths = service_plans["merged-modules"]
            merged_design = (repo / merged_paths["service_design"]).read_text(encoding="utf-8")
            self.assertIn("mvn -pl jeepay-core -am test", merged_design)
            self.assertIn("mvn -pl jeepay-service -am test", merged_design)
            self.assertTrue((repo / merged_paths["test_review_request"]).exists())
            self.assertTrue((repo / merged_paths["implementation_review_request"]).exists())
            self.assertTrue((repo / merged_paths["code_agent"]).exists())

            payment_paths = service_plans["jeepay-payment"]
            payment_design = (repo / payment_paths["service_design"]).read_text(encoding="utf-8")
            self.assertIn("mvn -pl jeepay-payment -am test", payment_design)

    def test_design_affected_services_accepts_table_and_comma_list(self) -> None:
        facts = {"service_candidates": ["services/refund-service", "services/ledger-service", "services/notice-service"]}
        design_text = textwrap.dedent(
            """
            # Refund Reconcile

            ## 影响服务
            | 服务 | 说明 |
            | --- | --- |
            | refund-service | refund state machine |
            | ledger-service | accounting journal |

            ## Affected services
            services: notice-service
            """
        ).strip()

        selected = orchestration_plan.services_from_design(design_text, facts)

        self.assertEqual(
            ["services/refund-service", "services/ledger-service", "services/notice-service"],
            selected,
        )

    def test_orchestration_status_uses_design_modules_for_service_plans(self) -> None:
        facts = {
            "service_candidates": ["jeepay-core", "jeepay-service", "jeepay-payment"],
            "multi_service": True,
            "design_docs_or_media_count": 0,
            "spring_entrypoints": [],
        }
        design_text = self._vnpay_risk_tiered_design()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "vnpay.md"
            design.parent.mkdir(parents=True)
            design.write_text(design_text, encoding="utf-8")

            result = e2e_dev_harness.orchestration_status(
                repo,
                "auto",
                design,
                run_date="2026-05-23",
                service_scope="auto",
                facts=facts,
            )

        self.assertEqual("affected", result["resolved_service_scope"])
        self.assertEqual(["jeepay-core", "jeepay-service", "jeepay-payment"], result["selected_services"])
        self.assertTrue(result["multi_agent_decision"]["use_multi_agent"])
        self.assertIn("multiple affected services/modules", result["multi_agent_decision"]["criteria"])
        # Only the risky payment module earns its own slice; low-risk core/service collapse into merged-modules.
        self.assertIn("jeepay-payment", result["handoff_artifacts"]["service_plans"])
        self.assertIn("merged-modules", result["handoff_artifacts"]["service_plans"])
        self.assertNotIn("jeepay-service", result["handoff_artifacts"]["service_plans"])
        self.assertIn("code-developer-jeepay-payment", [agent["name"] for agent in result["agents"]])
        code_agent = next(agent for agent in result["agents"] if agent["name"] == "code-developer-jeepay-payment")
        service_paths = result["handoff_artifacts"]["service_plans"]["jeepay-payment"]
        self.assertIn(service_paths["service_design"], code_agent["inputs"])
        self.assertIn(service_paths["test_impact_plan"], code_agent["inputs"])
        self.assertEqual("e2e-dev-harness.agent-schedule.v1", result["agent_schedule"]["schema"])
        self.assertTrue(any(task["parallel_group"] == "service:jeepay-payment" for task in result["agent_schedule"]["tasks"]))

    def test_plan_archive_creates_handoffs_for_design_affected_root_modules(self) -> None:
        design_text = self._vnpay_risk_tiered_design()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            repo.joinpath("pom.xml").write_text(
                textwrap.dedent(
                    """
                    <project xmlns="http://maven.apache.org/POM/4.0.0">
                      <modelVersion>4.0.0</modelVersion>
                      <modules>
                        <module>jeepay-core</module>
                        <module>jeepay-service</module>
                        <module>jeepay-payment</module>
                      </modules>
                    </project>
                    """
                ).strip(),
                encoding="utf-8",
            )
            for module in ("jeepay-core", "jeepay-service", "jeepay-payment"):
                module_dir = repo / module
                (module_dir / "src" / "main" / "java").mkdir(parents=True)
                (module_dir / "pom.xml").write_text("<project />", encoding="utf-8")
            design = repo / "docs" / "design" / "vnpay.md"
            design.parent.mkdir(parents=True)
            design.write_text(design_text, encoding="utf-8")
            args = SimpleNamespace(
                repo=repo,
                mode="auto",
                design_doc=design,
                agent_run_dir=None,
                run_date="2026-05-23",
                service_scope="auto",
                service=None,
                path=None,
                dependency_report=None,
                create_archive=True,
                write_exec_plan=None,
                status_file=None,
            )

            code, result = e2e_dev_harness.plan(args)

            self.assertEqual(0, code)
            self.assertEqual(["jeepay-core", "jeepay-payment", "jeepay-service"], sorted(result["selected_services"]))
            self.assertTrue((repo / result["handoff_artifacts"]["design_review_request"]).exists())
            self.assertTrue((repo / result["handoff_artifacts"]["test_review_request"]).exists())
            self.assertTrue((repo / result["handoff_artifacts"]["implementation_review_request"]).exists())
            self.assertFalse((repo / result["handoff_artifacts"]["design_review"]).exists())
            self.assertFalse((repo / result["handoff_artifacts"]["test_review"]).exists())
            self.assertFalse((repo / result["handoff_artifacts"]["implementation_review"]).exists())
            self.assertTrue((repo / result["handoff_artifacts"]["requirements_archive"]).exists())
            self.assertTrue((repo / result["handoff_artifacts"]["impact_summary"]).exists())
            self.assertTrue((repo / result["handoff_artifacts"]["impact_evidence"]).exists())
            self.assertTrue((repo / result["handoff_artifacts"]["artifact_registry"]).exists())
            self.assertTrue((repo / result["handoff_artifacts"]["agent_schedule"]).exists())
            self.assertTrue((repo / result["handoff_artifacts"]["run_state"]).exists())
            registry = json.loads((repo / result["handoff_artifacts"]["artifact_registry"]).read_text(encoding="utf-8"))
            schedule = json.loads((repo / result["handoff_artifacts"]["agent_schedule"]).read_text(encoding="utf-8"))
            state = json.loads((repo / result["handoff_artifacts"]["run_state"]).read_text(encoding="utf-8"))
            self.assertEqual("e2e-dev-harness.artifact-registry.v1", registry["schema"])
            self.assertEqual("e2e-dev-harness.agent-schedule.v1", schedule["schema"])
            self.assertEqual("e2e-dev-harness.run-state.v1", state["schema"])
            self.assertEqual("SERVICE_DESIGN_REQUIRED", state["lifecycle"])
            self.assertEqual("planned", state["gates"]["service_design"])
            self.assertEqual(result["handoff_artifacts"]["artifact_registry"], state["artifact_registry"])
            # Slice goes through run-state services; the merged low-risk modules go through shared edit scopes.
            self.assertEqual(["jeepay-payment"], state["services"])
            self.assertEqual(["jeepay-core/", "jeepay-service/"], state["shared_edit_scopes"])
            self.assertTrue(any(item["type"] == "design_doc" for item in registry["artifacts"]))
            archive_text = (repo / result["handoff_artifacts"]["requirements_archive"]).read_text(encoding="utf-8")
            self.assertIn("Final Clarified Requirement", archive_text)
            self.assertIn("Acceptance Criteria Status", archive_text)
            impact_text = (repo / result["handoff_artifacts"]["impact_summary"]).read_text(encoding="utf-8")
            self.assertIn("Raw Evidence", impact_text)
            self.assertIn("affected callers/consumers", impact_text)
            # Two slices on disk: one real (payment) plus one merged slice covering core + service. Every
            # slice still gets a service-design and forced R2/R3 review requests so coverage is preserved.
            service_plans = result["handoff_artifacts"]["service_plans"]
            self.assertEqual(["jeepay-payment", "merged-modules"], list(service_plans))
            for slice_id in ("jeepay-payment", "merged-modules"):
                paths = service_plans[slice_id]
                self.assertTrue((repo / paths["service_design"]).exists())
                service_design_text = (repo / paths["service_design"]).read_text(encoding="utf-8")
                self.assertIn("Primary development contract", service_design_text)
                self.assertIn("AC-1", service_design_text)
                self.assertTrue((repo / paths["service_plan"]).exists())
                self.assertTrue((repo / paths["code_agent"]).exists())
                self.assertTrue((repo / paths["implementation_manifest"]).exists())
                self.assertTrue((repo / paths["test_impact_plan"]).exists())
                self.assertTrue((repo / paths["test_review_request"]).exists())
                self.assertTrue((repo / paths["implementation_review_request"]).exists())
                self.assertFalse((repo / paths["test_review"]).exists())
                self.assertFalse((repo / paths["implementation_review"]).exists())
            payment_design = (repo / service_plans["jeepay-payment"]["service_design"]).read_text(encoding="utf-8")
            self.assertIn("mvn -pl jeepay-payment -am test", payment_design)
            merged_design = (repo / service_plans["merged-modules"]["service_design"]).read_text(encoding="utf-8")
            self.assertIn("mvn -pl jeepay-core -am test", merged_design)
            self.assertIn("mvn -pl jeepay-service -am test", merged_design)
            self.assertTrue((repo / result["handoff_artifacts"]["service_designs_dir"]).exists())
            self.assertTrue((repo / result["handoff_artifacts"]["verification_evidence"]).exists())

    def test_unmatched_requested_services_are_reported(self) -> None:
        facts = {"service_candidates": ["services/order-service"]}

        unmatched = orchestration_plan.unmatched_requested_services(facts, ["missing-service"])

        self.assertEqual(["missing-service"], unmatched)

    def test_select_services_affected_uses_only_path_service(self) -> None:
        facts = {"service_candidates": ["services/order-service", "services/payment-service", "services/catalog-service"]}

        selected, resolved_scope = orchestration_plan.select_services(
            facts,
            requested_services=None,
            requested_paths=["services/order-service/src/main/java/Order.java"],
            service_scope="auto",
        )

        self.assertEqual(["services/order-service"], selected)
        self.assertEqual("affected", resolved_scope)

    def test_select_services_all_keeps_full_service_candidates(self) -> None:
        facts = {"service_candidates": ["services/order-service", "services/payment-service"]}

        selected, resolved_scope = orchestration_plan.select_services(
            facts,
            requested_services=None,
            requested_paths=None,
            service_scope="all",
        )

        self.assertEqual(["services/order-service", "services/payment-service"], selected)
        self.assertEqual("all", resolved_scope)

    def test_mode_facts_discovery_do_not_treat_all_candidates_as_in_scope(self) -> None:
        facts = {
            "service_candidates": ["services/order-service", "services/payment-service"],
            "multi_service": True,
        }

        scoped = orchestration_plan.mode_facts_for_service_scope(facts, [], "discovery")
        selected, reasons = orchestration_plan.choose_mode("auto", scoped, "", False)

        self.assertEqual("single-review", selected)
        self.assertEqual([], scoped["service_candidates"])
        self.assertFalse(scoped["multi_service"])

    def test_artifacts_default_to_agent_run_archive(self) -> None:
        result = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        self.assertEqual("docs/agent-runs/2026-05-23-checkout", result["agent_run_dir"])
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/handoffs/01-requirements-clarifier.md",
            result["requirements"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/evidence/red-test.txt",
            result["red_test_evidence"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/evidence/coverage-matrix.md",
            result["coverage_matrix"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/evidence/impact-summary.md",
            result["impact_summary"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/evidence/impact-analysis.json",
            result["impact_evidence"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/requirements-archive.md",
            result["requirements_archive"],
        )

    def test_artifacts_allow_explicit_agent_run_dir(self) -> None:
        result = orchestration_plan.artifacts("checkout", agent_run_dir="docs/agent-runs/custom")

        self.assertEqual("docs/agent-runs/custom", result["agent_run_dir"])
        self.assertEqual("docs/agent-runs/custom/exec-plan.md", result["exec_plan"])

    def test_artifacts_include_service_level_plans(self) -> None:
        result = orchestration_plan.artifacts(
            "checkout",
            run_date="2026-05-23",
            services=["services/order-service", "services/payment-service"],
        )

        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-designs/order-service.md",
            result["service_plans"]["services/order-service"]["service_design"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-plans/order-service/implementation-plan.md",
            result["service_plans"]["services/order-service"]["service_plan"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-plans/payment-service/code-agent.md",
            result["service_plans"]["services/payment-service"]["code_agent"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-plans/payment-service/test-impact-plan.json",
            result["service_plans"]["services/payment-service"]["test_impact_plan"],
        )

    def test_plan_artifacts_include_rework_paths(self) -> None:
        result = orchestration_plan.artifacts(
            "checkout",
            run_date="2026-05-23",
            services=["services/order-service"],
        )

        self.assertEqual("docs/agent-runs/2026-05-23-checkout/rework", result["rework_dir"])
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-plans/order-service",
            result["service_plans"]["services/order-service"]["rework_dir"],
        )

    def test_plan_artifacts_include_semantic_review_paths(self) -> None:
        result = orchestration_plan.artifacts(
            "checkout",
            run_date="2026-05-23",
            services=["services/order-service"],
        )

        self.assertEqual("docs/agent-runs/2026-05-23-checkout/reviews", result["reviews_dir"])
        self.assertEqual("docs/agent-runs/2026-05-23-checkout/review-requests", result["review_requests_dir"])
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/review-requests/R1-design-review-request.md",
            result["design_review_request"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/reviews/R1-design-review.md",
            result["design_review"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-plans/order-service/review-requests/R3-implementation-review-request.md",
            result["service_plans"]["services/order-service"]["implementation_review_request"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-plans/order-service/reviews/R3-implementation-review.md",
            result["service_plans"]["services/order-service"]["implementation_review"],
        )

    def test_plan_artifacts_include_dependency_report_path(self) -> None:
        result = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/evidence/cross-service-dependencies.json",
            result["dependency_report"],
        )

    def test_plan_artifacts_include_contract_paths(self) -> None:
        result = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        self.assertEqual("docs/agent-runs/2026-05-23-checkout/contracts", result["contracts_dir"])
        self.assertEqual("docs/agent-runs/2026-05-23-checkout/contracts/<contract-id>.md", result["contract_pattern"])

    def test_plan_artifacts_include_run_summary_paths(self) -> None:
        result = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        self.assertEqual("docs/agent-runs/2026-05-23-checkout/run-summary.json", result["run_summary"])
        self.assertEqual("docs/agent-runs/2026-05-23-checkout/run-summary.md", result["run_summary_md"])
        self.assertEqual("docs/agent-runs/2026-05-23-checkout/execution-trace.json", result["execution_trace"])

    def test_plan_artifacts_include_test_impact_and_context_pack_paths(self) -> None:
        result = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/evidence/test-impact-plan.json",
            result["test_impact_plan"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/context-packs/<agent-or-task>.json",
            result["context_pack_pattern"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-designs",
            result["service_designs_dir"],
        )
        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/service-designs/<service>.md",
            result["service_design_pattern"],
        )

    def test_plan_artifacts_include_implementation_manifest_path(self) -> None:
        result = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        self.assertEqual(
            "docs/agent-runs/2026-05-23-checkout/evidence/implementation-manifest.md",
            result["implementation_manifest"],
        )

    def test_context_pack_builds_request_scoped_task_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            requirements = repo / "docs" / "agent-runs" / "run" / "handoffs" / "01-requirements-clarifier.md"
            requirements.parent.mkdir(parents=True)
            requirements.write_text("Requirement summary\n", encoding="utf-8")
            schedule = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "code-developer-order-service",
                                "phase": "implement",
                                "service": "services/order-service",
                                "inputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/implementation-manifest.md"],
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = context_pack.build_pack(repo, schedule, service="services/order-service", max_files=2, max_chars=1000)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("request-scoped; no inherited developer chat context", result["context_policy"])
        self.assertEqual(1, result["budget"]["input_files"])

    def test_context_pack_injects_service_memory_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            requirements = repo / "docs" / "agent-runs" / "run" / "handoffs" / "01-requirements-clarifier.md"
            requirements.parent.mkdir(parents=True)
            requirements.write_text("Requirement summary\n", encoding="utf-8")
            (repo / "services" / "order-service" / "src").mkdir(parents=True)
            memory_capture.init_memory(repo)
            (repo / "memory" / "decisions.md").write_text(
                textwrap.dedent(
                    """
                    # Decisions Memory

                    ## Entries

                    ### M-1

                    - Type: decision
                    - Source: design
                    - Confidence: verified
                    - Scope: services/order-service
                    - Phase: code
                    - Tags: #decision #service/order-service #phase/code
                    - Links: [[services/order-service]] [[AC-1]]
                    - Text: Order service owns quote timeout behavior.
                    """
                ).strip(),
                encoding="utf-8",
            )
            schedule = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "code-developer-order-service",
                                "phase": "implement",
                                "service": "services/order-service",
                                "changed_files": ["services/order-service/src/QuoteService.java"],
                                "inputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/implementation-manifest.md"],
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = context_pack.build_pack(repo, schedule, service="services/order-service", max_files=2, max_chars=1000)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("optional-context-not-authority", result["memory_policy"])
        self.assertFalse(result["memory_budget"]["truncated"])
        self.assertGreater(result["memory_budget"]["actual_chars"], 0)
        self.assertGreater(result["budget"]["input_bytes"], len("Requirement summary\n"))
        snippets = "\n".join(item["text"] for item in result["memory_context"]["snippets"])
        self.assertIn("quote timeout", snippets)
        self.assertIn("service+phase+path", result["memory_context"]["selection_reason"])

    def test_context_pack_marks_service_design_primary_for_code_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            service_design = repo / "docs" / "agent-runs" / "run" / "service-designs" / "order-service.md"
            service_plan = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service" / "implementation-plan.md"
            service_design.parent.mkdir(parents=True)
            service_plan.parent.mkdir(parents=True)
            service_design.write_text("# Service Design Slice: order-service\n", encoding="utf-8")
            service_plan.write_text("# Implementation Plan\n", encoding="utf-8")
            schedule = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T10",
                                "agent": "code-developer-order-service",
                                "phase": "implement",
                                "service": "services/order-service",
                                "inputs": [
                                    "docs/agent-runs/run/handoffs/01-requirements-clarifier.md",
                                    "docs/agent-runs/run/service-designs/order-service.md",
                                    "docs/agent-runs/run/service-plans/order-service/implementation-plan.md",
                                ],
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/code-agent.md"],
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = context_pack.build_pack(repo, schedule, task_id="T10", max_files=4, max_chars=1000)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(["docs/agent-runs/run/service-designs/order-service.md"], result["primary_inputs"])
        self.assertEqual("service-design-primary", result["input_contract"])

    def test_context_pack_blocks_outputs_outside_dir_graph_role_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".e2e").mkdir()
            (repo / ".e2e" / "dir-graph.yaml").write_text(
                "schema: e2e-dev-harness.dir-graph.v1\n"
                "skill_contracts:\n"
                "  - role: requirements-clarifier\n"
                "    write_scope: docs/agent-runs/<run>/handoffs\n",
                encoding="utf-8",
            )
            schedule = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule.parent.mkdir(parents=True)
            schedule.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "inputs": [],
                                "outputs": ["docs/agent-runs/run/implementation-plan.md"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = context_pack.build_pack(repo, schedule, agent="requirements-clarifier")

        self.assertFalse(result["ready"])
        self.assertTrue(any("dir graph role contract" in reason for reason in result["blocked_reasons"]))

    def test_context_pack_blocks_budget_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            requirements = repo / "docs" / "agent-runs" / "run" / "handoffs" / "01-requirements-clarifier.md"
            requirements.parent.mkdir(parents=True)
            requirements.write_text("x" * 50, encoding="utf-8")
            schedule = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "code-developer",
                                "phase": "implement",
                                "inputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
                                "outputs": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = context_pack.build_pack(repo, schedule, agent="code-developer", max_files=2, max_chars=10)

        self.assertFalse(result["ready"])
        self.assertTrue(any("above max_chars" in reason for reason in result["blocked_reasons"]))

    def test_runtime_capabilities_mark_claude_code_as_subagent_dispatcher(self) -> None:
        result = dispatcher.runtime_capabilities("claude-code")

        self.assertTrue(result["supports_subagent"])
        self.assertTrue(result["supports_task_hook"])
        self.assertTrue(result["supports_isolated_review"])
        self.assertEqual("native-subagent", result["dispatch_mode"])
        self.assertEqual("Task", result["spawn_tool"])
        self.assertTrue(result["spawn_requires_tool_call"])

    def test_runtime_capabilities_mark_codex_as_tool_spawn_dispatcher(self) -> None:
        result = dispatcher.runtime_capabilities("codex")

        self.assertTrue(result["supports_subagent"])
        self.assertTrue(result["supports_isolated_review"])
        self.assertEqual("codex-multi-agent-v1", result["dispatch_mode"])
        self.assertEqual("multi_agent_v1.spawn_agent", result["spawn_tool"])

    def test_dispatch_next_for_claude_returns_task_spawn_request_and_waits_for_hook_ack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            output = Path("docs/agent-runs/run/service-plans/order-service/code-agent.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, handoff)
            state = run_state.build_state(
                "docs/agent-runs/run",
                "multi",
                ["services/order-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T10",
                                "agent": "code-developer-order-service",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/order-service",
                                "inputs": [handoff.as_posix()],
                                "outputs": [output.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_next(
                repo,
                schedule,
                state_path,
                runtime="claude-code",
                coordinator_agent="coordinator-agent",
                developer_session="coordinator-session",
            )
            schedule_data = json.loads(schedule.read_text(encoding="utf-8"))
            updated_state = json.loads(state_path.read_text(encoding="utf-8"))
            context_pack_exists = (repo / result["context_pack"]).exists()
            invocation_exists = (repo / result["invocation_path"]).exists()

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("T10", result["task"]["id"])
        self.assertEqual("claimed", schedule_data["tasks"][0]["status"])
        self.assertEqual("code-developer-order-service", schedule_data["tasks"][0]["owner"])
        self.assertTrue(context_pack_exists)
        self.assertTrue(invocation_exists)
        self.assertEqual("awaiting_runtime_spawn", updated_state["dispatch"]["status"])
        self.assertEqual("T10", updated_state["dispatch"]["current_task_id"])
        self.assertTrue(result["requires_fresh_worker"])
        self.assertEqual("spawn_fresh_worker", result["coordinator_action"])
        self.assertIn("Use only the context pack", result["worker_context_policy"])
        self.assertIn("Task prompt", result["task_prompt"])
        self.assertIn("e2e-dev-harness isolated worker task", result["task_prompt"])
        self.assertIn("Coordinator must not execute this task", result["task_prompt"])
        self.assertIn("fresh isolated worker", result["task_prompt"])
        self.assertEqual("Task", result["runtime_spawn_request"]["tool"])
        self.assertEqual(result["task_prompt"], result["runtime_spawn_request"]["arguments"]["prompt"])
        self.assertIn("dispatch-ack", result["runtime_spawn_request"]["ack_command"])

    def test_dispatch_next_for_codex_returns_spawn_agent_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            output = Path("docs/agent-runs/run/service-plans/order-service/code-agent.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, handoff)
            state = run_state.build_state(
                "docs/agent-runs/run",
                "multi",
                ["services/order-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T10",
                                "agent": "code-developer-order-service",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/order-service",
                                "inputs": [handoff.as_posix()],
                                "outputs": [output.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_next(repo, schedule, state_path, runtime="codex")
            updated_state = json.loads(state_path.read_text(encoding="utf-8"))

        spawn = result["runtime_spawn_request"]
        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("awaiting_runtime_spawn", result["dispatch"]["status"])
        self.assertEqual("awaiting_runtime_spawn", updated_state["dispatch"]["status"])
        self.assertEqual("multi_agent_v1.spawn_agent", spawn["tool"])
        self.assertEqual("worker", spawn["arguments"]["agent_type"])
        self.assertFalse(spawn["arguments"]["fork_context"])
        self.assertEqual(result["task_prompt"], spawn["arguments"]["message"])
        self.assertIn("dispatch-complete", spawn["completion_command"])

    def test_cli_dispatch_next_blocks_when_context_budget_exceeded_without_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            output = Path("docs/agent-runs/run/service-plans/order-service/code-agent.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, handoff)
            state = run_state.build_state(
                "docs/agent-runs/run",
                "multi",
                ["services/order-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            run_state.write_state(repo, state_path, state)
            evidence_dir = run_dir / "evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "large.md").write_text(
                "x" * (session_checkpoint.DEFAULT_MAX_EVIDENCE_BYTES + 1),
                encoding="utf-8",
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T10",
                                "agent": "code-developer-order-service",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/order-service",
                                "inputs": [handoff.as_posix()],
                                "outputs": [output.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            code, result = e2e_dev_harness.dispatch_next(
                SimpleNamespace(
                    repo=repo,
                    schedule=schedule,
                    state=state_path,
                    runtime="codex",
                    coordinator_agent="coordinator-agent",
                    developer_session="coordinator-session",
                    max_files=12,
                    max_chars=120_000,
                    status_file=None,
                )
            )
            updated_schedule = json.loads(schedule.read_text(encoding="utf-8"))

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])
        self.assertTrue(result["coordinator_context_budget"]["handoff_recommended"])
        self.assertTrue(any("Session checkpoint" in reason for reason in result["blocked_reasons"]))
        self.assertEqual("planned", updated_schedule["tasks"][0]["status"])

    def test_cli_dispatch_next_allows_context_budget_exceeded_with_fresh_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            output = Path("docs/agent-runs/run/service-plans/order-service/code-agent.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, handoff)
            state = run_state.build_state(
                "docs/agent-runs/run",
                "multi",
                ["services/order-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            run_state.write_state(repo, state_path, state)
            evidence_dir = run_dir / "evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "large.md").write_text(
                "x" * (session_checkpoint.DEFAULT_MAX_EVIDENCE_BYTES + 1),
                encoding="utf-8",
            )
            session_checkpoint.create(repo, state_path)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T10",
                                "agent": "code-developer-order-service",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/order-service",
                                "inputs": [handoff.as_posix()],
                                "outputs": [output.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            with patch.object(
                coordinator_flow,
                "runtime_hook_status",
                return_value={"ready": True, "runtime": "codex", "warnings": []},
            ):
                code, result = e2e_dev_harness.dispatch_next(
                    SimpleNamespace(
                        repo=repo,
                        schedule=schedule,
                        state=state_path,
                        runtime="codex",
                        coordinator_agent="coordinator-agent",
                        developer_session="coordinator-session",
                        max_files=12,
                        max_chars=120_000,
                        status_file=None,
                    )
                )

        self.assertEqual(0, code, result["blocked_reasons"])
        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(result["coordinator_context_budget"]["handoff_recommended"])
        self.assertEqual("T10", result["task"]["id"])

    def test_cli_dispatch_next_blocks_with_install_hook_guidance_when_hooks_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            role_template = Path("docs/agent-runs/run/agent-roles/test-case-developer.md")
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            output = Path("docs/agent-runs/run/test-plan.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, handoff)
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single-review",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "execution_model": "coordinator-only-dispatch",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "test-case-developer",
                                "phase": "tdd-red",
                                "role_group": "test",
                                "inputs": [handoff.as_posix()],
                                "outputs": [output.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            code, result = e2e_dev_harness.dispatch_next(
                SimpleNamespace(
                    repo=repo,
                    schedule=schedule,
                    state=state_path,
                    runtime="codex",
                    coordinator_agent="coordinator-agent",
                    developer_session="coordinator-session",
                    max_files=12,
                    max_chars=120000,
                    status_file=None,
                )
            )
            updated = json.loads(state_path.read_text(encoding="utf-8"))
            summary = json.loads((state_path.parent / "coordinator-summary.json").read_text(encoding="utf-8"))

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])
        self.assertIn("hook_status", result)
        self.assertEqual("generic", result["hook_status"]["runtime"])
        self.assertTrue(any("install_hooks" in reason for reason in result["blocked_reasons"]))
        self.assertEqual("PLANNED", updated["lifecycle"])
        self.assertFalse(summary["ready"])
        self.assertIn("install_hooks", result["next_single_action"])
        self.assertNotIn("dispatch", result)
        self.assertNotIn("runtime_spawn_request", result)
        self.assertTrue(any("hook" in warning.lower() for warning in result["warnings"]))

    def test_dispatch_beat_writes_spawn_request_and_prompt_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            output = Path("docs/agent-runs/run/service-plans/order-service/code-agent.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, handoff)
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state(
                    "docs/agent-runs/run",
                    "multi",
                    ["services/order-service"],
                    "docs/agent-runs/run/artifact-registry.json",
                    "IMPLEMENTED",
                ),
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T10",
                                "agent": "code-developer-order-service",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/order-service",
                                "inputs": [handoff.as_posix()],
                                "outputs": [output.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_beat(repo, schedule, state_path, runtime="claude-code", max_workers=1)
            packet = result["dispatch_packets"][0]
            spawn_path = repo / packet["spawn_request_path"]
            prompt_path = repo / packet["task_prompt_path"]
            spawn_path_exists = spawn_path.exists()
            prompt_path_exists = prompt_path.exists()
            spawn_payload = json.loads(spawn_path.read_text(encoding="utf-8"))
            prompt_text = prompt_path.read_text(encoding="utf-8")

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(spawn_path_exists)
        self.assertTrue(prompt_path_exists)
        self.assertEqual("Task", spawn_payload["tool"])
        self.assertIn("dispatch-ack", spawn_payload["ack_command"])
        self.assertIn("Task prompt: e2e-dev-harness isolated worker task", prompt_text)
        self.assertEqual(packet["runtime_spawn_request"], result["runtime_spawn_requests"][0])

    def test_dispatch_beat_spawns_parallel_ready_tasks_in_distinct_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, handoff)
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state(
                    "docs/agent-runs/run",
                    "multi",
                    ["services/order-service", "services/payment-service"],
                    "docs/agent-runs/run/artifact-registry.json",
                    "IMPLEMENTED",
                ),
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T10",
                                "agent": "code-developer-order-service",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/order-service",
                                "parallel_group": "service:order-service",
                                "inputs": [handoff.as_posix()],
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/code-agent.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            },
                            {
                                "id": "T11",
                                "agent": "code-developer-payment-service",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/payment-service",
                                "parallel_group": "service:payment-service",
                                "inputs": [handoff.as_posix()],
                                "outputs": ["docs/agent-runs/run/service-plans/payment-service/code-agent.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            },
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_beat(repo, schedule, state_path, runtime="codex", max_workers=4)
            schedule_data = json.loads(schedule.read_text(encoding="utf-8"))
            updated_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(["T10", "T11"], [task["id"] for task in result["claimed_tasks"]])
        self.assertEqual(2, len(result["runtime_spawn_requests"]))
        self.assertEqual({"T10", "T11"}, set(updated_state["dispatches"]))
        self.assertEqual("awaiting_runtime_spawn", updated_state["dispatches"]["T10"]["status"])
        self.assertEqual("awaiting_runtime_spawn", updated_state["dispatches"]["T11"]["status"])
        self.assertEqual("claimed", schedule_data["tasks"][0]["status"])
        self.assertEqual("claimed", schedule_data["tasks"][1]["status"])
        self.assertEqual("T11", updated_state["dispatch"]["current_task_id"])

    def test_dispatch_state_update_repairs_missing_lifecycle_from_phase_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state(
                    "docs/agent-runs/run",
                    "single-review",
                    [],
                    "docs/agent-runs/run/artifact-registry.json",
                    "PLANNED",
                ),
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state.pop("lifecycle")
            state_path.write_text(json.dumps(state), encoding="utf-8")

            result = dispatcher.update_dispatch_state(
                repo,
                state_path,
                {
                    "status": "worker_completed",
                    "current_task_id": "T01",
                    "current_agent": "test-case-developer",
                },
            )
            updated_state = json.loads(state_path.read_text(encoding="utf-8"))
            lock = json.loads((run_dir / run_state.PHASE_LOCK).read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("PLANNED", updated_state["lifecycle"])
        self.assertEqual("PLANNED", lock["lifecycle"])
        self.assertIn("Recovered missing run-state lifecycle", " ".join(result["warnings"]))

    def test_dispatch_beat_spawns_parallel_service_tdd_red_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            role_template = Path("docs/agent-runs/run/agent-roles/test-case-developer.md")
            write_role_template(repo, role_template)
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state(
                    "docs/agent-runs/run",
                    "multi",
                    ["services/order-service", "services/payment-service"],
                    "docs/agent-runs/run/artifact-registry.json",
                    "PLANNED",
                ),
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {"id": "T01", "agent": "use-case-designer", "phase": "design", "status": "completed"},
                            {"id": "T02", "agent": "design-reviewer", "phase": "r1-review", "status": "completed"},
                            {
                                "id": "T20",
                                "agent": "test-case-developer-order-service",
                                "phase": "tdd-red",
                                "role_group": "test",
                                "service": "services/order-service",
                                "parallel_group": "service:services/order-service",
                                "depends_on_phases": ["design", "r1-review"],
                                "inputs": ["docs/agent-runs/run/service-designs/order-service.md"],
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/red-test-evidence.txt"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            },
                            {
                                "id": "T21",
                                "agent": "test-case-developer-payment-service",
                                "phase": "tdd-red",
                                "role_group": "test",
                                "service": "services/payment-service",
                                "parallel_group": "service:services/payment-service",
                                "depends_on_phases": ["design", "r1-review"],
                                "inputs": ["docs/agent-runs/run/service-designs/payment-service.md"],
                                "outputs": ["docs/agent-runs/run/service-plans/payment-service/red-test-evidence.txt"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            },
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_beat(repo, schedule, state_path, runtime="codex", max_workers=4)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(["T20", "T21"], [task["id"] for task in result["claimed_tasks"]])
        self.assertEqual(2, len(result["runtime_spawn_requests"]))

    def test_dispatch_beat_planned_lifecycle_dispatches_unfinished_r1_before_tdd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            review_template = Path("docs/agent-runs/run/agent-roles/semantic-reviewer.md")
            test_template = Path("docs/agent-runs/run/agent-roles/test-case-developer.md")
            request = run_dir / "review-requests" / "R1-design-review-request.md"
            review = run_dir / "reviews" / "R1-design-review.md"
            test_plan = run_dir / "handoffs" / "03-test-case-developer.md"
            write_role_template(repo, review_template)
            write_role_template(repo, test_template)
            request.parent.mkdir(parents=True, exist_ok=True)
            request.write_text("Review request\nreviewer_invocation: docs/agent-runs/run/review-invocations/r1.json\n", encoding="utf-8")
            test_plan.parent.mkdir(parents=True, exist_ok=True)
            test_plan.write_text("# Test plan\n", encoding="utf-8")
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state(
                    "docs/agent-runs/run",
                    "single-review",
                    [],
                    "docs/agent-runs/run/artifact-registry.json",
                    "PLANNED",
                ),
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "selected_mode": "single-review",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "status": "completed",
                            },
                            {
                                "id": "T02",
                                "agent": "use-case-designer",
                                "phase": "design",
                                "status": "completed",
                            },
                            {
                                "id": "T03",
                                "agent": "single-reviewer-r1-design",
                                "phase": "r1-review",
                                "role_group": "review",
                                "depends_on_phases": ["design"],
                                "inputs": [request.relative_to(repo).as_posix()],
                                "outputs": [review.relative_to(repo).as_posix()],
                                "role_template": review_template.as_posix(),
                                "status": "planned",
                            },
                            {
                                "id": "T04",
                                "agent": "test-case-developer",
                                "phase": "tdd-red",
                                "role_group": "test",
                                "depends_on_phases": ["design", "r1-review", "plan"],
                                "inputs": [test_plan.relative_to(repo).as_posix()],
                                "outputs": ["docs/agent-runs/run/evidence/red-test.txt"],
                                "role_template": test_template.as_posix(),
                                "status": "planned",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_beat(repo, schedule, state_path, runtime="claude-code", max_workers=1)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(["T03"], [task["id"] for task in result["claimed_tasks"]])
        self.assertEqual("single-reviewer-r1-design", result["runtime_spawn_requests"][0]["agent"])

    def test_dispatch_beat_in_planned_skips_stale_early_tasks_and_spawns_service_tdd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            test_template = Path("docs/agent-runs/run/agent-roles/test-case-developer.md")
            design_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            review_template = Path("docs/agent-runs/run/agent-roles/semantic-reviewer.md")
            for template in (test_template, design_template, review_template):
                write_role_template(repo, template)
            for service in ("order-service", "payment-service"):
                design = run_dir / "service-designs" / f"{service}.md"
                plan = run_dir / "service-plans" / service / "implementation-plan.md"
                design.parent.mkdir(parents=True, exist_ok=True)
                plan.parent.mkdir(parents=True, exist_ok=True)
                design.write_text(f"# Service Design Slice: services/{service}\n", encoding="utf-8")
                plan.write_text(f"# Implementation Plan: services/{service}\n", encoding="utf-8")
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state(
                    "docs/agent-runs/run",
                    "multi",
                    ["services/order-service", "services/payment-service"],
                    "docs/agent-runs/run/artifact-registry.json",
                    "PLANNED",
                ),
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "selected_mode": "multi",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "role_group": "design",
                                "parallel_group": "clarify",
                                "role_template": design_template.as_posix(),
                                "status": "planned",
                            },
                            {
                                "id": "T02",
                                "agent": "use-case-designer",
                                "phase": "design",
                                "role_group": "design",
                                "parallel_group": "design",
                                "depends_on_phases": ["clarify"],
                                "role_template": design_template.as_posix(),
                                "status": "planned",
                            },
                            {
                                "id": "T04",
                                "agent": "design-reviewer",
                                "phase": "r1-review",
                                "role_group": "review",
                                "parallel_group": "r1-review",
                                "depends_on_phases": ["design"],
                                "role_template": review_template.as_posix(),
                                "status": "completed",
                            },
                            {
                                "id": "T20",
                                "agent": "test-case-developer-order-service",
                                "phase": "tdd-red",
                                "role_group": "test",
                                "service": "services/order-service",
                                "parallel_group": "service:services/order-service",
                                "depends_on_phases": ["design", "r1-review"],
                                "inputs": [
                                    "docs/agent-runs/run/handoffs/01-requirements-clarifier.md",
                                    "docs/agent-runs/run/handoffs/02-use-case-designer.md",
                                    "docs/agent-runs/run/handoffs/03-test-case-developer.md",
                                    "docs/agent-runs/run/service-designs/order-service.md",
                                    "docs/agent-runs/run/service-plans/order-service/implementation-plan.md",
                                ],
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/red-test-evidence.txt"],
                                "role_template": test_template.as_posix(),
                                "status": "planned",
                            },
                            {
                                "id": "T21",
                                "agent": "test-case-developer-payment-service",
                                "phase": "tdd-red",
                                "role_group": "test",
                                "service": "services/payment-service",
                                "parallel_group": "service:services/payment-service",
                                "depends_on_phases": ["design", "r1-review"],
                                "inputs": [
                                    "docs/agent-runs/run/handoffs/01-requirements-clarifier.md",
                                    "docs/agent-runs/run/handoffs/02-use-case-designer.md",
                                    "docs/agent-runs/run/handoffs/03-test-case-developer.md",
                                    "docs/agent-runs/run/service-designs/payment-service.md",
                                    "docs/agent-runs/run/service-plans/payment-service/implementation-plan.md",
                                ],
                                "outputs": ["docs/agent-runs/run/service-plans/payment-service/red-test-evidence.txt"],
                                "role_template": test_template.as_posix(),
                                "status": "planned",
                            },
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_beat(repo, schedule, state_path, runtime="codex", max_workers=4)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(["T20", "T21"], [task["id"] for task in result["claimed_tasks"]])
        self.assertEqual(2, len(result["runtime_spawn_requests"]))
        self.assertTrue(all(task["phase"] == "tdd-red" for task in result["claimed_tasks"]))

    def test_dispatch_beat_does_not_parallelize_same_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, handoff)
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state("docs/agent-runs/run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED"),
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T10",
                                "agent": "code-developer-order-a",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/order-service",
                                "parallel_group": "service:order-service",
                                "inputs": [handoff.as_posix()],
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/code-agent-a.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            },
                            {
                                "id": "T11",
                                "agent": "code-developer-order-b",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/order-service",
                                "parallel_group": "service:order-service",
                                "inputs": [handoff.as_posix()],
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/code-agent-b.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_beat(repo, schedule, state_path, runtime="claude-code", max_workers=4)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(["T10"], [task["id"] for task in result["claimed_tasks"]])
        self.assertEqual(1, len(result["runtime_spawn_requests"]))
        self.assertTrue(any(item["task_id"] == "T11" and "parallel group" in item["blocked_reasons"][0] for item in result["blocked_tasks"]))

    def test_dispatch_beat_does_not_redispatch_active_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, handoff)
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state("docs/agent-runs/run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED"),
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T10",
                                "agent": "code-developer-order-service",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/order-service",
                                "parallel_group": "service:order-service",
                                "inputs": [handoff.as_posix()],
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/code-agent.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            first = dispatcher.dispatch_beat(repo, schedule, state_path, runtime="codex", max_workers=1)

            second = dispatcher.dispatch_beat(repo, schedule, state_path, runtime="codex", max_workers=1)

        self.assertTrue(first["ready"], first["blocked_reasons"])
        self.assertFalse(second["ready"])
        self.assertTrue(any("active dispatch" in reason for item in second["blocked_tasks"] for reason in item["blocked_reasons"]))

    def test_dispatch_beat_does_not_dispatch_new_task_in_active_parallel_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, handoff)
            state = run_state.build_state("docs/agent-runs/run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED")
            state["dispatches"] = {
                "T10": {
                    "status": "worker_running",
                    "current_task_id": "T10",
                    "current_agent": "code-developer-order-a",
                    "parallel_group": "service:order-service",
                    "worker_handle": "worker-a",
                }
            }
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T11",
                                "agent": "code-developer-order-b",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/order-service",
                                "parallel_group": "service:order-service",
                                "inputs": [handoff.as_posix()],
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/code-agent-b.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_beat(repo, schedule, state_path, runtime="claude-code", max_workers=2)

        self.assertFalse(result["ready"])
        self.assertTrue(any("active dispatch" in reason for item in result["blocked_tasks"] for reason in item["blocked_reasons"]))

    def test_dispatch_beat_reports_recent_completion_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            event = run_dir / "dispatch-events" / "T10-completed.json"
            event.parent.mkdir(parents=True, exist_ok=True)
            event.write_text(json.dumps({"task_id": "T10", "event": "worker_completed"}), encoding="utf-8")
            run_state.write_state(repo, state_path, run_state.build_state("docs/agent-runs/run", "multi", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED"))
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(json.dumps({"schema": "e2e-dev-harness.agent-schedule.v1", "tasks": []}), encoding="utf-8")

            result = dispatcher.dispatch_beat(repo, schedule, state_path, runtime="codex", max_workers=2)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(["T10"], [item["task_id"] for item in result["recent_events"]])

    def test_dispatch_ack_records_real_spawned_worker_handle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "multi",
                ["services/order-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            state["dispatch"] = {
                "status": "awaiting_runtime_spawn",
                "runtime": "codex",
                "current_task_id": "T10",
                "current_agent": "code-developer-order-service",
                "invocation_path": "docs/agent-runs/run/dispatch-invocations/T10.json",
                "context_pack": "docs/agent-runs/run/context-packs/T10.json",
            }
            run_state.write_state(repo, state_path, state)

            result = dispatcher.dispatch_ack(
                repo,
                state_path,
                task_id="T10",
                agent="code-developer-order-service",
                worker_handle="019-worker",
                worker_session="codex-thread-019-worker",
            )
            updated_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("worker_running", updated_state["dispatch"]["status"])
        self.assertEqual("019-worker", updated_state["dispatch"]["worker_handle"])
        self.assertEqual("codex-thread-019-worker", updated_state["dispatch"]["worker_session"])

    def test_dispatch_ack_blocks_coordinator_session_as_worker_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            invocation = run_dir / "dispatch-invocations" / "T10-code-developer.json"
            invocation.parent.mkdir(parents=True, exist_ok=True)
            invocation.write_text(
                json.dumps(
                    {
                        "developer_agent": "coordinator-agent",
                        "developer_session": "coordinator-session",
                        "worker_agent": "code-developer",
                        "worker_session": "code-developer-session",
                    }
                ),
                encoding="utf-8",
            )
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "WAITING_DISPATCH",
            )
            state["dispatch"] = {
                "status": "awaiting_runtime_spawn",
                "runtime": "codex",
                "current_task_id": "T10",
                "current_agent": "code-developer",
                "invocation_path": "docs/agent-runs/run/dispatch-invocations/T10-code-developer.json",
            }
            state["dispatches"] = {"T10": state["dispatch"]}
            run_state.write_state(repo, state_path, state)

            result = dispatcher.dispatch_ack(
                repo,
                state_path,
                task_id="T10",
                agent="code-developer",
                worker_handle="coordinator-agent",
                worker_session="coordinator-session",
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("coordinator session" in reason.lower() for reason in result["blocked_reasons"]))

    def test_dispatch_ack_updates_matching_dispatch_slot_not_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            state = run_state.build_state("docs/agent-runs/run", "multi", [], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED")
            state["dispatch"] = {"status": "awaiting_runtime_spawn", "current_task_id": "T11", "current_agent": "agent-b"}
            state["dispatches"] = {
                "T10": {"status": "awaiting_runtime_spawn", "runtime": "codex", "current_task_id": "T10", "current_agent": "agent-a"},
                "T11": {"status": "awaiting_runtime_spawn", "runtime": "codex", "current_task_id": "T11", "current_agent": "agent-b"},
            }
            run_state.write_state(repo, state_path, state)

            result = dispatcher.dispatch_ack(repo, state_path, "T10", "agent-a", "worker-a", "session-a")
            updated_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("worker_running", updated_state["dispatches"]["T10"]["status"])
        self.assertEqual("awaiting_runtime_spawn", updated_state["dispatches"]["T11"]["status"])
        self.assertEqual("T10", updated_state["dispatch"]["current_task_id"])

    def test_dispatch_ack_syncs_worker_session_to_invocation_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            invocation = run_dir / "review-invocations" / "R1-design-review-invocation.json"
            invocation.parent.mkdir(parents=True, exist_ok=True)
            invocation.write_text(
                json.dumps(
                    {
                        "runtime": "claude-code",
                        "invocation_type": "subagent",
                        "developer_agent": "coordinator-agent",
                        "reviewer_agent": "design-reviewer",
                        "worker_agent": "design-reviewer",
                        "developer_session": "coordinator-session",
                        "reviewer_session": "design-reviewer-session",
                        "worker_session": "design-reviewer-session",
                        "context_pack": "docs/agent-runs/run/context-packs/T04.json",
                        "task_id": "T04",
                        "fork_context": False,
                        "context_policy": "request-only; no-inherited developer chat context",
                        "status": "dispatched",
                    }
                ),
                encoding="utf-8",
            )
            state = run_state.build_state(
                "docs/agent-runs/run",
                "single-review",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            state["dispatch"] = {
                "status": "awaiting_runtime_spawn",
                "runtime": "claude-code",
                "current_task_id": "T04",
                "current_agent": "design-reviewer",
                "invocation_path": "docs/agent-runs/run/review-invocations/R1-design-review-invocation.json",
                "context_pack": "docs/agent-runs/run/context-packs/T04.json",
            }
            run_state.write_state(repo, state_path, state)

            result = dispatcher.dispatch_ack(
                repo,
                state_path,
                task_id="T04",
                agent="design-reviewer",
                worker_handle="claude-task-123",
                worker_session="claude-task-session-123",
            )
            invocation_data = json.loads(invocation.read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("claude-task-session-123", invocation_data["worker_session"])
        self.assertEqual("claude-task-session-123", invocation_data["reviewer_session"])
        self.assertEqual("claude-task-123", invocation_data["worker_handle"])
        self.assertEqual("running", invocation_data["status"])

    def test_dispatch_complete_blocks_unconfirmed_spawned_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/service-plans/order-service/code-agent.md")
            role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, evidence, "code-developer-order-service")
            state = run_state.build_state(
                "docs/agent-runs/run",
                "multi",
                ["services/order-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            state["dispatch"] = {
                "status": "awaiting_runtime_spawn",
                "runtime": "claude-code",
                "current_task_id": "T10",
                "current_agent": "code-developer-order-service",
                "invocation_path": "docs/agent-runs/run/dispatch-invocations/T10-code-developer-order-service.json",
                "context_pack": "docs/agent-runs/run/context-packs/T10.json",
            }
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T10",
                                "agent": "code-developer-order-service",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/order-service",
                                "inputs": [],
                                "outputs": [evidence.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "code-developer-order-service",
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_complete(repo, schedule, state_path, "T10", "code-developer-order-service", [evidence.as_posix()])

        self.assertFalse(result["ready"])
        self.assertTrue(any("not been confirmed" in reason for reason in result["blocked_reasons"]))

    def test_dispatch_complete_blocks_task_that_was_never_dispatched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/service-plans/order-service/code-agent.md")
            role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, evidence, "code-developer-order-service")
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state(
                    "docs/agent-runs/run",
                    "multi",
                    ["services/order-service"],
                    "docs/agent-runs/run/artifact-registry.json",
                    "IMPLEMENTED",
                ),
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T10",
                                "agent": "code-developer-order-service",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/order-service",
                                "inputs": [],
                                "outputs": [evidence.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "code-developer-order-service",
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_complete(repo, schedule, state_path, "T10", "code-developer-order-service", [evidence.as_posix()])
            schedule_data = json.loads(schedule.read_text(encoding="utf-8"))

        self.assertFalse(result["ready"])
        self.assertTrue(any("never dispatched" in reason for reason in result["blocked_reasons"]))
        self.assertEqual("claimed", schedule_data["tasks"][0]["status"])

    def test_dispatch_complete_uses_matching_dispatch_slot_and_writes_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            evidence_a = Path("docs/agent-runs/run/handoffs/a.md")
            evidence_b = Path("docs/agent-runs/run/handoffs/b.md")
            role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, evidence_a, "agent-a")
            write_ready_handoff(repo, evidence_b, "agent-b")
            state = run_state.build_state("docs/agent-runs/run", "multi", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            state["dispatch"] = {"status": "worker_running", "current_task_id": "T11", "current_agent": "agent-b", "worker_handle": "worker-b"}
            state["dispatches"] = {
                "T10": {"status": "worker_running", "runtime": "codex", "current_task_id": "T10", "current_agent": "agent-a", "worker_handle": "worker-a"},
                "T11": {"status": "worker_running", "runtime": "codex", "current_task_id": "T11", "current_agent": "agent-b", "worker_handle": "worker-b"},
            }
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T10",
                                "agent": "agent-a",
                                "phase": "design",
                                "role_group": "design",
                                "inputs": [],
                                "outputs": [evidence_a.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "agent-a",
                            },
                            {
                                "id": "T11",
                                "agent": "agent-b",
                                "phase": "design",
                                "role_group": "design",
                                "inputs": [],
                                "outputs": [evidence_b.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "agent-b",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_complete(repo, schedule, state_path, "T10", "agent-a", [evidence_a.as_posix()])
            updated_state = json.loads(state_path.read_text(encoding="utf-8"))
            event = json.loads((run_dir / "dispatch-events" / "T10-completed.json").read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("worker_completed", updated_state["dispatches"]["T10"]["status"])
        self.assertEqual("worker_running", updated_state["dispatches"]["T11"]["status"])
        self.assertEqual("T10", event["task_id"])
        self.assertEqual([evidence_a.as_posix()], event["evidence"])
        self.assertTrue(any(item["task_id"] == "T11" for item in event["unblocked_candidates"]))

    def test_dispatch_complete_blocks_coordinator_session_as_worker_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            invocation = run_dir / "dispatch-invocations" / "T10-code-developer.json"
            evidence = Path("docs/agent-runs/run/evidence/code-result.txt")
            role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
            write_role_template(repo, role_template)
            (repo / evidence).parent.mkdir(parents=True, exist_ok=True)
            (repo / evidence).write_text("done\n", encoding="utf-8")
            invocation.parent.mkdir(parents=True, exist_ok=True)
            invocation.write_text(
                json.dumps(
                    {
                        "developer_agent": "coordinator-agent",
                        "developer_session": "coordinator-session",
                        "worker_agent": "code-developer",
                        "worker_session": "code-developer-session",
                    }
                ),
                encoding="utf-8",
            )
            state = run_state.build_state("docs/agent-runs/run", "single", [], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED")
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "current_task_id": "T10",
                "current_agent": "code-developer",
                "worker_handle": "coordinator-agent",
                "worker_session": "coordinator-session",
                "invocation_path": "docs/agent-runs/run/dispatch-invocations/T10-code-developer.json",
            }
            state["dispatches"] = {"T10": state["dispatch"]}
            run_state.write_state(repo, state_path, state)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T10",
                                "agent": "code-developer",
                                "phase": "implement",
                                "role_group": "code",
                                "outputs": [evidence.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "code-developer",
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_complete(repo, schedule, state_path, "T10", "code-developer", [evidence.as_posix()])

        self.assertFalse(result["ready"])
        self.assertTrue(any("coordinator session" in reason.lower() for reason in result["blocked_reasons"]))

    def test_dispatch_next_budget_block_does_not_claim_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            role_template = Path("docs/agent-runs/run/agent-roles/use-case-designer.md")
            large_input = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, large_input)
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state("docs/agent-runs/run", "single-review", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED"),
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                # tdd-red @ PLANNED passes the dispatch phase guard; this
                                # task is merely the vehicle to reach the context-pack
                                # budget check below (forced by max_chars=10).
                                "id": "T02",
                                "agent": "use-case-designer",
                                "phase": "tdd-red",
                                "role_group": "tdd",
                                "inputs": [large_input.as_posix()],
                                "outputs": ["docs/agent-runs/run/handoffs/02-use-case-designer.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_next(repo, schedule, state_path, runtime="claude-code", max_chars=10)
            schedule_data = json.loads(schedule.read_text(encoding="utf-8"))

        self.assertFalse(result["ready"])
        self.assertTrue(any("Context pack" in reason for reason in result["blocked_reasons"]))
        self.assertEqual("planned", schedule_data["tasks"][0]["status"])
        self.assertNotIn("owner", schedule_data["tasks"][0])

    def test_dispatch_next_enters_waiting_dispatch_without_subagent_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state("docs/agent-runs/run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "PLANNED"),
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "test-case-developer",
                                "phase": "tdd-red",
                                "inputs": [],
                                "outputs": ["docs/agent-runs/run/evidence/red-test.txt"],
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_next(repo, schedule, state_path, runtime="manual")
            updated_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertFalse(result["ready"])
        self.assertEqual("waiting_dispatch", result["dispatch"]["status"])
        self.assertEqual("PLANNED", updated_state["lifecycle"])
        self.assertEqual("waiting_dispatch", updated_state["dispatch"]["status"])
        self.assertIn("manual_dispatch_packet", result)
        self.assertTrue(result["requires_fresh_worker"])
        self.assertEqual("pause_for_manual_worker", result["coordinator_action"])
        self.assertIn("fresh manual worker", result["worker_context_policy"])
        packet = result["manual_worker_packet"]
        self.assertEqual("T01", packet["task_id"])
        self.assertEqual("test-case-developer", packet["agent"])
        self.assertEqual(["docs/agent-runs/run/evidence/red-test.txt"], packet["outputs"])
        self.assertIn("dispatch-ack", packet["next_commands"][0])
        self.assertIn("dispatch-finish", packet["next_commands"][-1])
        self.assertTrue(any("coordinator context" in item for item in packet["forbidden_actions"]))
        self.assertIn("next_commands", result)
        self.assertIn("forbidden_artifact_writes", result)

    def test_dispatch_next_skips_blocked_task_and_claims_next_ready_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
            ready_handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            missing_handoff = "docs/agent-runs/run/handoffs/missing.md"
            write_role_template(repo, role_template)
            write_ready_handoff(repo, ready_handoff)
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state("docs/agent-runs/run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED"),
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "code-developer-blocked",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/order-service",
                                "inputs": [missing_handoff],
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/blocked.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            },
                            {
                                "id": "T02",
                                "agent": "code-developer-ready",
                                "phase": "implement",
                                "role_group": "code",
                                "service": "services/order-service",
                                "inputs": [ready_handoff.as_posix()],
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/code-agent.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_next(repo, schedule, state_path, runtime="claude-code")
            schedule_data = json.loads(schedule.read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("T02", result["task"]["id"])
        self.assertEqual("planned", schedule_data["tasks"][0]["status"])
        self.assertEqual("claimed", schedule_data["tasks"][1]["status"])
        self.assertTrue(any(item["task_id"] == "T01" for item in result["skipped_tasks"]))

    def test_artifact_repair_task_can_target_stale_input_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            stale_handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            write_ready_handoff(repo, stale_handoff)
            evidence = repo / "docs" / "agent-runs" / "run" / "evidence" / "requirements-summary.md"
            evidence.write_text("Requirements clarification evidence changed after handoff.\n", encoding="utf-8")
            normal_task = {
                "id": "T02",
                "agent": "implementation-planner",
                "phase": "plan",
                "inputs": [stale_handoff.as_posix()],
                "outputs": ["docs/agent-runs/run/handoffs/02-implementation-plan.md"],
            }
            repair_task = {
                **normal_task,
                "id": "T01b",
                "agent": "requirements-clarifier",
                "phase": "clarify",
                "kind": "artifact_repair",
                "repair_targets": [stale_handoff.as_posix()],
            }

            normal_blockers = dispatcher.task_ready_blockers(repo, {"tasks": [normal_task]}, normal_task, "implementation-planner", {})
            repair_blockers = dispatcher.task_ready_blockers(repo, {"tasks": [repair_task]}, repair_task, "requirements-clarifier", {})

        self.assertTrue(any("input handoff is not ready" in reason for reason in normal_blockers))
        self.assertEqual([], repair_blockers)

    def test_artifact_repair_task_cannot_bypass_unclaimed_stale_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            stale_handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            other_handoff = Path("docs/agent-runs/run/handoffs/02-use-case-designer.md")
            write_ready_handoff(repo, stale_handoff)
            write_ready_handoff(repo, other_handoff, "use-case-designer")
            evidence = repo / "docs" / "agent-runs" / "run" / "evidence" / "requirements-summary.md"
            evidence.write_text("Requirements clarification evidence changed after handoff.\n", encoding="utf-8")
            task = {
                "id": "T01b",
                "agent": "requirements-clarifier",
                "phase": "clarify",
                "kind": "artifact_repair",
                "inputs": [stale_handoff.as_posix(), other_handoff.as_posix()],
                "outputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
                "repair_targets": [other_handoff.as_posix()],
            }

            blockers = dispatcher.task_ready_blockers(repo, {"tasks": [task]}, task, "requirements-clarifier", {})

        self.assertTrue(any("input handoff is not ready" in reason for reason in blockers))

    def test_clarify_creates_mechanical_repair_task_for_oversized_impact_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            schedule_path = run_dir / "agent-schedule.json"
            role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            design_path = repo / "docs" / "design" / "feature.md"
            run_dir.mkdir(parents=True)
            design_path.parent.mkdir(parents=True)
            write_role_template(repo, role_template)
            long_note = " ".join("caller-impact" for _ in range(260))
            design_path.write_text(
                textwrap.dedent(
                    f"""
                    # Feature

                    ## Restated Intent
                    - The user wants a refund callback API.
                    - User confirmation: confirmed-by: user @2026-06-05-session.

                    ## Goal
                    - Add a refund callback API.

                    ## Scope
                    - services/payment-service

                    ## Use Cases
                    - Merchant calls HTTP refund callback endpoint.

                    ## Acceptance Criteria
                    - AC-1 POST /api/refunds/callback returns accepted status.

                    ## Change Logic
                    - Current behavior: no public refund callback endpoint exists.
                    - Target behavior: POST /api/refunds/callback accepts merchant refund callback requests.
                    - Runtime path: RefundCallbackController -> RefundCallbackService -> RefundRepository.
                    - State/data effect: persists refund status field and response body.

                    ## Impact Summary
                    - Source: GitNexus impact + dependency scanner
                    - Raw Evidence: docs/agent-runs/run/evidence/impact-analysis.json
                    - Notes: {long_note}

                    | type | interface | affected callers/consumers | related AC | required tests/contracts | risk |
                    | --- | --- | --- | --- | --- | --- |
                    | HTTP | POST /api/refunds/callback | merchant-admin | AC-1 | controller contract test | medium |

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None. confirmed-by: user @2026-06-05-session.
                    """
                ).strip(),
                encoding="utf-8",
            )
            state = run_state.build_state(
                "docs/agent-runs/run",
                "bootstrap",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            run_state.write_state(repo, state_path, state)
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "status": "completed",
                                "outputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            (run_dir / "dispatch-events").mkdir()
            (run_dir / "dispatch-events" / "T01-completed.json").write_text(
                json.dumps({"event": "worker_completed", "task_id": "T01", "agent": "requirements-clarifier"}),
                encoding="utf-8",
            )

            code, result = e2e_dev_harness.clarify(
                SimpleNamespace(
                    repo=repo,
                    design_doc=design_path,
                    run_state=state_path,
                    require_intent=True,
                    require_user_confirmation=True,
                    status_file=None,
                )
            )
            schedule_after = json.loads(schedule_path.read_text(encoding="utf-8"))
            state_after = json.loads(state_path.read_text(encoding="utf-8"))

        repair_tasks = [task for task in schedule_after["tasks"] if task.get("kind") == "artifact_repair"]
        self.assertEqual(0, code)
        self.assertEqual("CLARIFIED", state_after["lifecycle"])
        self.assertFalse(result["interaction_required"])
        self.assertTrue(result["agent_remediation_required"])
        self.assertEqual("dispatch_mechanical_repair", result["next_agent_action"])
        self.assertEqual("mechanical_repair", result["next_required"]["gate"])
        self.assertEqual(1, len(repair_tasks))
        self.assertEqual("T01b", repair_tasks[0]["id"])
        self.assertEqual("clarify", repair_tasks[0]["phase"])
        self.assertEqual(role_template.as_posix(), repair_tasks[0]["role_template"])
        self.assertEqual("requirements-clarifier", repair_tasks[0]["role_template_key"])
        self.assertEqual([Path("docs/design/feature.md").as_posix()], repair_tasks[0]["repair_targets"])

    def test_dispatch_beat_dispatches_created_mechanical_repair_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            schedule_path = run_dir / "agent-schedule.json"
            role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            design_path = repo / "docs" / "design" / "feature.md"
            run_dir.mkdir(parents=True)
            design_path.parent.mkdir(parents=True)
            write_role_template(repo, role_template)
            design_path.write_text("# Feature\n\n## Impact Summary\n- oversized\n", encoding="utf-8")
            state = run_state.build_state(
                "docs/agent-runs/run",
                "bootstrap",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "CREATED",
            )
            run_state.write_state(repo, state_path, state)
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "status": "completed",
                                "outputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
                            },
                            {
                                "id": "T01b",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "kind": "artifact_repair",
                                "repair_code": "impact_summary_table_incomplete",
                                "repair_section": "Impact Summary",
                                "objective": "Complete the bounded Impact Summary table.",
                                "constraints": [
                                    "Do not add new product facts or reopen user-confirmed Open Questions.",
                                ],
                                "status": "planned",
                                "inputs": ["docs/design/feature.md"],
                                "outputs": ["docs/design/feature.md"],
                                "repair_targets": ["docs/design/feature.md"],
                                "role_template": role_template.as_posix(),
                                "role_template_key": "requirements-clarifier",
                            },
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_beat(repo, schedule_path, state_path, runtime="codex", max_workers=1)

        self.assertTrue(result["ready"], result)
        self.assertEqual([{"id": "T01b", "agent": "requirements-clarifier", "phase": "clarify", "service": ""}], result["claimed_tasks"])
        prompt = result["dispatch_packets"][0]["task_prompt"]
        self.assertIn("Write only scheduled outputs", prompt)
        self.assertIn("docs/design/feature.md", prompt)
        self.assertIn("Artifact repair contract:", prompt)
        self.assertIn("repair_code: impact_summary_table_incomplete", prompt)
        self.assertIn("repair_section: Impact Summary", prompt)
        self.assertIn("Repair only the listed repair_targets", prompt)
        self.assertIn("Do not add, rename, reopen, or answer Open Questions/OQ items", prompt)
        self.assertIn("This is a bounded repair of existing scheduled artifacts, not a new clarification pass", prompt)

    def test_dispatch_next_blocks_task_with_phase_not_allowed_for_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            role_template = Path("docs/agent-runs/run/agent-roles/use-case-designer.md")
            write_role_template(repo, role_template)
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state("docs/agent-runs/run", "multi", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED"),
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T02",
                                "agent": "use-case-designer",
                                "phase": "",
                                "role_group": "design",
                                "role_template": role_template.as_posix(),
                                "inputs": [],
                                "outputs": ["docs/agent-runs/run/handoffs/02-use-case-designer.md"],
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_next(repo, schedule, state_path, runtime="claude-code")
            schedule_data = json.loads(schedule.read_text(encoding="utf-8"))

        self.assertFalse(result["ready"])
        blocked_reasons = [reason for item in result["blocked_tasks"] for reason in item["blocked_reasons"]]
        self.assertTrue(any("Task phase <missing> is not dispatchable while lifecycle is CLARIFIED" in reason for reason in blocked_reasons), blocked_reasons)
        self.assertEqual("planned", schedule_data["tasks"][0]["status"])

    def test_dispatch_next_service_design_skips_satisfied_global_design_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            use_case_template = Path("docs/agent-runs/run/agent-roles/use-case-designer.md")
            service_template = Path("docs/agent-runs/run/agent-roles/service-designer.md")
            write_role_template(repo, use_case_template)
            write_role_template(repo, service_template)
            write_ready_handoff(repo, Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md"))
            write_ready_handoff(repo, Path("docs/agent-runs/run/handoffs/02-use-case-designer.md"), "use-case-designer")
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state(
                    "docs/agent-runs/run",
                    "multi",
                    [],
                    "docs/agent-runs/run/artifact-registry.json",
                    "SERVICE_DESIGN_REQUIRED",
                ),
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T02",
                                "agent": "use-case-designer",
                                "phase": "design",
                                "role_group": "design",
                                "role_template": use_case_template.as_posix(),
                                "inputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
                                "outputs": ["docs/agent-runs/run/handoffs/02-use-case-designer.md"],
                                "status": "planned",
                                "requires_runtime_dispatch": True,
                            },
                            {
                                "id": "T03",
                                "agent": "design-reviewer",
                                "phase": "r1-review",
                                "role_group": "review",
                                "role_template": service_template.as_posix(),
                                "inputs": ["docs/agent-runs/run/handoffs/02-use-case-designer.md"],
                                "outputs": ["docs/agent-runs/run/reviews/R1-design-review.md"],
                                "status": "planned",
                                "requires_runtime_dispatch": True,
                            },
                            {
                                "id": "T06",
                                "agent": "service-designer-jeepay-core",
                                "phase": "design",
                                "service": "jeepay-core",
                                "role_group": "service-design",
                                "role_template": service_template.as_posix(),
                                "inputs": [
                                    "docs/agent-runs/run/handoffs/01-requirements-clarifier.md",
                                    "docs/agent-runs/run/handoffs/02-use-case-designer.md",
                                ],
                                "outputs": ["docs/agent-runs/run/service-designs/jeepay-core.md"],
                                "status": "planned",
                                "requires_runtime_dispatch": True,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_next(repo, schedule, state_path, runtime="claude-code")
            schedule_data = json.loads(schedule.read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("T06", result["task"]["id"])
        self.assertEqual("planned", schedule_data["tasks"][0]["status"])
        self.assertEqual("planned", schedule_data["tasks"][1]["status"])
        self.assertEqual("claimed", schedule_data["tasks"][2]["status"])
        self.assertTrue(
            any(
                item["task_id"] == "T02" and "already satisfied" in item["blocked_reasons"][0]
                for item in result["blocked_tasks"]
            ),
            result["blocked_tasks"],
        )
        self.assertTrue(any(item["task_id"] == "T03" for item in result["blocked_tasks"]))

    def test_dispatch_status_reports_lifecycle_ready_next_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            use_case_template = Path("docs/agent-runs/run/agent-roles/use-case-designer.md")
            service_template = Path("docs/agent-runs/run/agent-roles/service-designer.md")
            write_role_template(repo, use_case_template)
            write_role_template(repo, service_template)
            write_ready_handoff(repo, Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md"))
            write_ready_handoff(repo, Path("docs/agent-runs/run/handoffs/02-use-case-designer.md"), "use-case-designer")
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state(
                    "docs/agent-runs/run",
                    "multi",
                    [],
                    "docs/agent-runs/run/artifact-registry.json",
                    "SERVICE_DESIGN_REQUIRED",
                ),
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "role_template": use_case_template.as_posix(),
                                "inputs": [],
                                "outputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
                                "status": "planned",
                            },
                            {
                                "id": "T02",
                                "agent": "use-case-designer",
                                "phase": "design",
                                "role_group": "design",
                                "role_template": use_case_template.as_posix(),
                                "inputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
                                "outputs": ["docs/agent-runs/run/handoffs/02-use-case-designer.md"],
                                "status": "completed",
                            },
                            {
                                "id": "T03",
                                "agent": "design-reviewer",
                                "phase": "r1-review",
                                "role_group": "review",
                                "role_template": service_template.as_posix(),
                                "inputs": ["docs/agent-runs/run/handoffs/02-use-case-designer.md"],
                                "outputs": ["docs/agent-runs/run/reviews/R1-design-review.md"],
                                "status": "planned",
                            },
                            {
                                "id": "T06",
                                "agent": "service-designer-jeepay-core",
                                "phase": "design",
                                "service": "jeepay-core",
                                "role_group": "service-design",
                                "role_template": service_template.as_posix(),
                                "inputs": [
                                    "docs/agent-runs/run/handoffs/01-requirements-clarifier.md",
                                    "docs/agent-runs/run/handoffs/02-use-case-designer.md",
                                ],
                                "outputs": ["docs/agent-runs/run/service-designs/jeepay-core.md"],
                                "status": "planned",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_status(repo, schedule, state_path)

        self.assertEqual("T06", result["next_task"])
        self.assertEqual("T06", result["ready_tasks"][0]["id"])
        self.assertEqual("T01", result["open_tasks"][0]["id"])
        self.assertTrue(any(item["task_id"] == "T03" for item in result["blocked_tasks"]))

    def test_dispatch_status_can_write_manual_recovery_request_for_user_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            evidence = run_dir / "service-plans" / "order-service" / "unit-test-evidence.txt"
            request_path = run_dir / "recovery-requests" / "T03.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("passed\n", encoding="utf-8")
            evidence_ref = evidence.relative_to(repo).as_posix()
            state = run_state.build_state("run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED")
            state["dispatches"] = {
                "T03": {
                    "status": "worker_running",
                    "current_task_id": "T03",
                    "current_agent": "code-developer-order-service",
                    "worker_handle": "manual-worker-T03",
                    "worker_session": "manual-worker-session-T03",
                    "spawn_confirmed_by": "dispatch_ack",
                }
            }
            state["dispatch"] = state["dispatches"]["T03"]
            run_state.write_state(repo, state_path, state)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "tasks": [
                            {
                                "id": "T03",
                                "phase": "implement",
                                "agent": "code-developer-order-service",
                                "service": "services/order-service",
                                "status": "claimed",
                                "owner": "code-developer-order-service",
                                "outputs": [evidence_ref],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            code, result = e2e_dev_harness.dispatch_status(
                SimpleNamespace(
                    repo=repo,
                    schedule=schedule,
                    state=state_path,
                    write_recovery_request=request_path,
                    task_id="T03",
                    agent="code-developer-order-service",
                    evidence=[evidence_ref],
                    status_file=None,
                )
            )
            request = json.loads(request_path.read_text(encoding="utf-8"))

        self.assertEqual(0, code)
        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(str(request_path), result["recovery_request_path"])
        self.assertFalse(request["approved"])
        self.assertEqual("T03", request["task_id"])
        self.assertEqual("code-developer-order-service", request["agent"])
        self.assertIn(evidence_ref, request["allowed_evidence"])
        self.assertIn(evidence_ref, request["evidence_hashes"])

    def test_dispatch_complete_runs_reviewer_gate_for_review_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            review = Path("docs/agent-runs/run/reviews/R1-design-review.md")
            role_template = Path("docs/agent-runs/run/agent-roles/semantic-reviewer.md")
            write_role_template(repo, role_template)
            (repo / review).parent.mkdir(parents=True, exist_ok=True)
            (repo / review).write_text("review evidence\n", encoding="utf-8")
            state = run_state.build_state("docs/agent-runs/run", "single-review", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "current_task_id": "T04",
                "current_agent": "design-reviewer",
                "worker_handle": "review-worker",
                "worker_session": "review-worker-session",
                "spawn_acknowledged_at": "2026-05-31T00:00:00Z",
            }
            state["dispatches"] = {"T04": state["dispatch"]}
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T04",
                                "agent": "design-reviewer",
                                "phase": "r1-review",
                                "role_group": "review",
                                "inputs": ["docs/agent-runs/run/review-requests/R1-design-review-request.md"],
                                "outputs": [review.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "design-reviewer",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(dispatcher.reviewer_gate, "validate", return_value={"ready": True, "blocked_reasons": [], "warnings": [], "covered_phases": ["design"]}) as validate:
                result = dispatcher.dispatch_complete(repo, schedule, state_path, "T04", "design-reviewer", [review.as_posix()])

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertIn("reviewer_gate", result)
        validate.assert_called_once()

    def test_dispatch_complete_satisfies_strict_schedule_and_transitions_red_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            review = Path("docs/agent-runs/run/reviews/R2-test-review.md")
            role_template = Path("docs/agent-runs/run/agent-roles/semantic-reviewer.md")
            write_role_template(repo, role_template)
            (repo / review).parent.mkdir(parents=True, exist_ok=True)
            (repo / review).write_text("review evidence\n", encoding="utf-8")
            state = run_state.build_state("docs/agent-runs/run", "single-review", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "current_task_id": "T02",
                "current_agent": "test-reviewer",
                "worker_handle": "review-worker",
                "worker_session": "review-worker-session",
                "spawn_acknowledged_at": "2026-05-31T00:00:00Z",
            }
            state["dispatches"] = {"T02": state["dispatch"]}
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "require_role_templates": True,
                        "tasks": [
                            {"id": "T01", "agent": "test-case-developer", "phase": "tdd-red", "status": "completed"},
                            {
                                "id": "T02",
                                "agent": "test-reviewer",
                                "phase": "r2-review",
                                "role_group": "review",
                                "inputs": ["docs/agent-runs/run/review-requests/R2-test-review-request.md"],
                                "outputs": [review.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "test-reviewer",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            event_dir = run_dir / "dispatch-events"
            event_dir.mkdir(parents=True, exist_ok=True)
            (event_dir / "T01-completed.json").write_text(
                json.dumps({"event": "worker_completed", "task_id": "T01", "agent": "test-case-developer"}),
                encoding="utf-8",
            )

            with patch.object(dispatcher.reviewer_gate, "validate", return_value={"ready": True, "blocked_reasons": [], "warnings": [], "covered_phases": ["test"]}):
                result = dispatcher.dispatch_complete(repo, schedule, state_path, "T02", "test-reviewer", [review.as_posix()])
            updated = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("RED_READY", updated["lifecycle"])
        self.assertEqual("RED_READY", result["run_state_transition"]["lifecycle"])

    def test_dispatch_complete_restores_previous_lifecycle_after_waiting_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, evidence, "requirements-agent")
            state = run_state.build_state("docs/agent-runs/run", "bootstrap", [], "docs/agent-runs/run/artifact-registry.json", "WAITING_DISPATCH")
            state["dispatch"] = {
                "status": "waiting_dispatch",
                "runtime": "manual",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
            }
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "role_group": "design",
                                "inputs": [],
                                "outputs": [evidence.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            ack = dispatcher.dispatch_ack(
                repo,
                state_path,
                task_id="T01",
                agent="requirements-clarifier",
                worker_handle="manual-worker-1",
                worker_session="manual-session-1",
            )
            result = dispatcher.dispatch_complete(repo, schedule, state_path, "T01", "requirements-clarifier", [evidence.as_posix()])
            updated_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(ack["ready"], ack["blocked_reasons"])
        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("CREATED", updated_state["lifecycle"])
        self.assertEqual("worker_completed", updated_state["dispatch"]["status"])

    def test_dispatch_complete_blocks_phase_guard_auto_confirmed_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, evidence, "requirements-agent")
            state = run_state.build_state("docs/agent-runs/run", "bootstrap", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "previous_lifecycle": "CREATED",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "phase-guard-auto-confirm:T01",
                "worker_session": "phase-guard-auto-confirm:T01",
                "spawn_confirmed_by": "phase_guard",
                "spawn_acknowledged_at": "2026-06-04T00:00:00Z",
            }
            state["dispatches"] = {"T01": state["dispatch"]}
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "role_group": "design",
                                "inputs": [],
                                "outputs": [evidence.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_complete(repo, schedule, state_path, "T01", "requirements-clarifier", [evidence.as_posix()])
            updated_schedule = json.loads(schedule.read_text(encoding="utf-8"))

        self.assertFalse(result["ready"])
        self.assertTrue(any("phase_guard" in reason for reason in result["blocked_reasons"]))
        self.assertEqual("claimed", updated_schedule["tasks"][0]["status"])

    def test_dispatch_complete_requirements_clarifier_returns_clarify_next_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/requirements.md")
            (repo / evidence).parent.mkdir(parents=True, exist_ok=True)
            (repo / evidence).write_text("# Requirements\n\n## Restated Intent\nReady.\n", encoding="utf-8")
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "tasks": [
                            {
                                "id": "T01",
                                "phase": "clarify",
                                "agent": "requirements-clarifier",
                                "status": "planned",
                                "outputs": [evidence.as_posix()],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = complete_dispatched_task(
                repo,
                schedule,
                state_path,
                "T01",
                "requirements-clarifier",
                [evidence.as_posix()],
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("clarification", result["next_required"]["phase"])
        self.assertIn(" clarify ", result["next_required"]["command"])
        self.assertIn("--run-state", result["next_required"]["command"])

    def test_dispatch_complete_explains_ready_handoff_body_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            write_role_template(repo, role_template)
            handoff = repo / evidence
            handoff.parent.mkdir(parents=True, exist_ok=True)
            impact_evidence = Path("docs/agent-runs/run/evidence/requirements-summary.md")
            (repo / impact_evidence).parent.mkdir(parents=True, exist_ok=True)
            (repo / impact_evidence).write_text("requirements evidence\n", encoding="utf-8")
            handoff.write_text(
                textwrap.dedent(
                    """
                    ---
                    agent: requirements-clarifier
                    agent_id: requirements-agent-1
                    status: ready
                    inputs:
                      - user request
                    outputs:
                      - docs/agent-runs/run/evidence/requirements-summary.md
                    input_hashes:
                      - user-request sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
                    output_hashes:
                      - docs/agent-runs/run/evidence/requirements-summary.md sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
                    consumed_by:
                      - implementation-planner
                    open_questions: None
                    ---

                    # Agent Handoff
                    """
                ).strip(),
                encoding="utf-8",
            )
            state = run_state.build_state("run", "bootstrap", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "requirements-worker",
                "worker_session": "requirements-worker-session",
            }
            state["dispatches"] = {"T01": state["dispatch"]}
            run_state.write_state(repo, state_path, state)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "phase": "clarify",
                                "agent": "requirements-clarifier",
                                "role_group": "design",
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                                "outputs": [evidence.as_posix(), impact_evidence.as_posix()],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_complete(repo, schedule, state_path, "T01", "requirements-clarifier", [evidence.as_posix()])

        self.assertFalse(result["ready"])
        self.assertEqual("ready_handoff_contract", result["missing_evidence_type"])
        self.assertIn("handoff_completion_requirements", result)
        self.assertIn("Summary", result["handoff_completion_requirements"]["required_body_sections"])
        self.assertTrue(any(".ready.json" in item for item in result["handoff_completion_requirements"]["required_steps"]))
        self.assertTrue(any("ready body section" in reason for reason in result["blocked_reasons"]))
        self.assertEqual("CREATED", result["lifecycle"])
        self.assertEqual("CLARIFY", result["workflow_stage"])
        self.assertEqual(
            {
                "code_writes_allowed": False,
                "required_action": "spawn_or_resume_worker",
                "worker_owned_outputs": [evidence.as_posix(), impact_evidence.as_posix()],
            },
            {
                "code_writes_allowed": result["coordinator_action"]["code_writes_allowed"],
                "required_action": result["coordinator_action"]["required_action"],
                "worker_owned_outputs": result["coordinator_action"]["worker_owned_outputs"],
            },
        )
        self.assertEqual([evidence.as_posix(), impact_evidence.as_posix()], result["forbidden_artifact_writes"])
        self.assertEqual([evidence.as_posix(), impact_evidence.as_posix()], result["worker_owned_outputs"])
        self.assertFalse(any("coordinator" in command.lower() and "write" in command.lower() for command in result["next_commands"]))
        self.assertTrue(any("dispatch-finish" in command for command in result["next_commands"]))

    def test_dispatch_complete_ready_marker_only_mismatch_returns_dispatch_finish_primary_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, evidence, "requirements-agent")
            marker = repo / evidence.with_suffix(".ready.json")
            marker_data = json.loads(marker.read_text(encoding="utf-8"))
            marker_data["sha256"] = "0" * 64
            marker.write_text(json.dumps(marker_data), encoding="utf-8")
            state = run_state.build_state("run", "bootstrap", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "requirements-worker",
                "worker_session": "requirements-worker-session",
                "spawn_confirmed_by": "dispatch_ack",
                "spawn_acknowledged_at": "2026-06-06T00:00:00Z",
            }
            state["dispatches"] = {"T01": state["dispatch"]}
            run_state.write_state(repo, state_path, state)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "phase": "clarify",
                                "agent": "requirements-clarifier",
                                "role_group": "design",
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                                "outputs": [evidence.as_posix()],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_complete(repo, schedule, state_path, "T01", "requirements-clarifier", [evidence.as_posix()])

        self.assertFalse(result["ready"])
        self.assertEqual("ready_handoff_contract", result["missing_evidence_type"])
        self.assertEqual("dispatch-finish", result["coordinator_action"]["required_action"])
        self.assertIn("dispatch-finish", result["next_required"]["primary_command"])
        self.assertIn("--handoff docs/agent-runs/run/handoffs/01-requirements-clarifier.md", result["next_required"]["primary_command"])
        self.assertFalse(result["coordinator_action"]["code_writes_allowed"])

    def test_dispatch_complete_missing_ready_marker_returns_dispatch_finish_primary_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, evidence, "requirements-agent")
            (repo / evidence.with_suffix(".ready.json")).unlink()
            state = run_state.build_state("run", "bootstrap", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "requirements-worker",
                "worker_session": "requirements-worker-session",
                "spawn_confirmed_by": "dispatch_ack",
                "spawn_acknowledged_at": "2026-06-06T00:00:00Z",
            }
            state["dispatches"] = {"T01": state["dispatch"]}
            run_state.write_state(repo, state_path, state)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "phase": "clarify",
                                "agent": "requirements-clarifier",
                                "role_group": "design",
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                                "outputs": [evidence.as_posix()],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_complete(repo, schedule, state_path, "T01", "requirements-clarifier", [evidence.as_posix()])

        self.assertFalse(result["ready"])
        self.assertEqual("ready_handoff_contract", result["missing_evidence_type"])
        self.assertEqual("dispatch-finish", result["coordinator_action"]["required_action"])
        self.assertEqual("dispatch_finish", result["next_required"]["phase"])
        self.assertIn("ready_marker_missing", result["blocker_codes"])

    def test_dispatch_complete_ready_handoff_mechanical_repair_returns_artifact_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, evidence, "requirements-agent")
            handoff = repo / evidence
            handoff_text = handoff.read_text(encoding="utf-8")
            handoff_text = handoff_text.replace(
                "outputs:\n  - docs/agent-runs/run/evidence/requirements-summary.md",
                f"outputs:\n  - {evidence.as_posix()}",
            ).replace(
                "output_hashes:\n  - docs/agent-runs/run/evidence/requirements-summary.md",
                f"output_hashes:\n  - {evidence.as_posix()}",
            ).replace(
                "## Open Questions\nNone",
                "## Open Questions\nAll previously raised questions are resolved.",
            )
            handoff.write_text(handoff_text, encoding="utf-8")
            marker = repo / evidence.with_suffix(".ready.json")
            marker_data = json.loads(marker.read_text(encoding="utf-8"))
            marker_data["sha256"] = hashlib.sha256(handoff.read_bytes()).hexdigest()
            marker.write_text(json.dumps(marker_data), encoding="utf-8")
            state = run_state.build_state("run", "bootstrap", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "requirements-worker",
                "worker_session": "requirements-worker-session",
                "spawn_confirmed_by": "dispatch_ack",
                "spawn_acknowledged_at": "2026-06-06T00:00:00Z",
            }
            state["dispatches"] = {"T01": state["dispatch"]}
            run_state.write_state(repo, state_path, state)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "phase": "clarify",
                                "agent": "requirements-clarifier",
                                "role_group": "design",
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                                "outputs": [evidence.as_posix()],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = dispatcher.dispatch_complete(repo, schedule, state_path, "T01", "requirements-clarifier", [evidence.as_posix()])

        self.assertFalse(result["ready"])
        self.assertEqual("ready_handoff_contract", result["missing_evidence_type"])
        self.assertEqual("artifact_repair", result["coordinator_action"]["required_action"])
        self.assertEqual("artifact_repair", result["next_required"]["phase"])
        self.assertFalse(result["coordinator_action"]["code_writes_allowed"])
        self.assertEqual([evidence.as_posix()], result["forbidden_artifact_writes"])
        self.assertIn("self_referential_outputs", result["blocker_codes"])
        self.assertIn("open_questions_not_literal_none", result["blocker_codes"])

    def test_task_prompt_includes_ready_handoff_contract_for_handoff_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            invocation = run_dir / "dispatch-invocations" / "T01-requirements-clarifier.json"
            invocation.parent.mkdir(parents=True, exist_ok=True)
            pack = {
                "context_pack_path": "docs/agent-runs/run/context-packs/T01.json",
                "allowed_inputs": ["user request"],
                "allowed_outputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
            }

            prompt = dispatcher.task_prompt(
                {"id": "T01", "agent": "requirements-clarifier", "phase": "clarify"},
                pack,
                invocation,
                repo,
            )

        self.assertIn("Ready handoff contract", prompt)
        self.assertIn(".ready.json", prompt)
        self.assertIn("Summary, Facts Used, Decisions Made, Open Questions, Downstream Assumptions, Verification Evidence", prompt)
        self.assertIn("Do not hand-roll python", prompt)
        self.assertIn("e2e_dev_harness.py hash", prompt)
        self.assertIn("dispatch-finish --handoff", prompt)
        self.assertIn("all declared input/output artifacts", prompt)
        self.assertIn("stable Markdown", prompt)
        self.assertIn("last completion step", prompt)
        self.assertNotIn("handoff --path", prompt)
        self.assertNotIn("Compute SHA-256 hashes", prompt)

    def test_task_prompt_routes_missing_inputs_out_of_input_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            invocation = run_dir / "dispatch-invocations" / "T01-requirements-clarifier.json"
            invocation.parent.mkdir(parents=True, exist_ok=True)
            pack = {
                "context_pack_path": "docs/agent-runs/run/context-packs/T01.json",
                "allowed_inputs": [
                    "user request",
                    "docs/design/feature.md",
                    "docs/agent-runs/run/evidence/cross-service-dependencies.json",
                ],
                "resolved_input_files": [{"path": "docs/design/feature.md", "bytes": 10}],
                "missing_input_files": [
                    {"path": "docs/agent-runs/run/evidence/cross-service-dependencies.json", "reason": "missing"}
                ],
                "allowed_outputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
            }

            prompt = dispatcher.task_prompt(
                {"id": "T01", "agent": "requirements-clarifier", "phase": "clarify"},
                pack,
                invocation,
                repo,
            )

        self.assertIn("Resolved input files for input_hashes:", prompt)
        self.assertIn("Missing allowed inputs:", prompt)
        self.assertIn("Never write sha256:missing", prompt)
        self.assertIn("Under ## Open Questions, write exactly None and no other text", prompt)

    def test_manual_worker_packet_includes_ready_handoff_contract_for_handoff_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            task = {
                "id": "T01",
                "agent": "requirements-clarifier",
                "outputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
            }
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(json.dumps({"tasks": [task]}), encoding="utf-8")
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state("run", "bootstrap", [], "docs/agent-runs/run/artifact-registry.json", "CREATED"),
            )

            packet = dispatcher.manual_worker_packet(repo, schedule, state_path, task)

        self.assertIn("handoff_completion_requirements", packet)
        self.assertIn("Summary", packet["handoff_completion_requirements"]["required_body_sections"])
        steps = "\n".join(packet["handoff_completion_requirements"]["required_steps"])
        self.assertIn("Do not hand-roll python", steps)
        self.assertIn("e2e_dev_harness.py hash", steps)
        self.assertNotIn("Compute SHA-256 hashes", steps)
        # The packet must steer the worker to dispatch-finish, which runs handoff
        # finalize before dispatch-complete, with the concrete path.
        self.assertTrue(
            any(
                "dispatch-finish" in command and "--handoff" in command and "--agent" in command
                for command in packet["next_commands"]
            )
        )
        self.assertTrue(
            any("01-requirements-clarifier.md" in command for command in packet["next_commands"])
        )

    def test_dispatch_complete_summary_surfaces_clarify_next_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            run_state.write_state(
                repo,
                state_path,
                run_state.build_state("run", "bootstrap", [], "docs/agent-runs/run/artifact-registry.json", "CREATED"),
            )
            args = SimpleNamespace(repo=repo, state=state_path, full_json=False)
            result = {
                "ready": True,
                "next_required": {
                    "phase": "clarification",
                    "command": "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py clarify . --run-state docs/agent-runs/run/run-state.json",
                },
            }

            summary = e2e_dev_harness.summarize_stdout_result("dispatch-complete", args, result)

        self.assertEqual("clarification", summary["next_action"]["phase"])
        self.assertIn(" clarify ", summary["next_action"]["command"])
        self.assertIn(" clarify ", summary["next_command"])

    def test_dispatch_complete_service_design_returns_service_design_next_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/service-designs/order-service.md")
            (repo / evidence).parent.mkdir(parents=True, exist_ok=True)
            (repo / evidence).write_text("# Service Design Slice: services/order-service\n", encoding="utf-8")
            state = run_state.build_state(
                "run",
                "multi",
                ["services/order-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "SERVICE_DESIGN_REQUIRED",
            )
            run_state.write_state(repo, state_path, state)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "tasks": [
                            {
                                "id": "T01",
                                "phase": "design",
                                "agent": "service-designer-order-service",
                                "service": "services/order-service",
                                "status": "planned",
                                "outputs": [evidence.as_posix()],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = complete_dispatched_task(
                repo,
                schedule,
                state_path,
                "T01",
                "service-designer-order-service",
                [evidence.as_posix()],
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("service_design", result["next_required"]["phase"])
        self.assertIn(" service-design ", result["next_required"]["command"])
        self.assertIn("--run-state", result["next_required"]["command"])

    def test_dispatch_complete_code_developer_returns_ac_progress_next_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            evidence = Path("docs/agent-runs/run/service-plans/order-service/unit-test-evidence.txt")
            (repo / evidence).parent.mkdir(parents=True, exist_ok=True)
            (repo / evidence).write_text("passed\n", encoding="utf-8")
            state = run_state.build_state(
                "run",
                "multi",
                ["services/order-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            run_state.write_state(repo, state_path, state)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "tasks": [
                            {
                                "id": "T01",
                                "phase": "implement",
                                "agent": "code-developer-order-service",
                                "service": "services/order-service",
                                "status": "planned",
                                "outputs": [evidence.as_posix()],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = complete_dispatched_task(
                repo,
                schedule,
                state_path,
                "T01",
                "code-developer-order-service",
                [evidence.as_posix()],
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("ac_progress", result["next_required"]["phase"])
        self.assertIn(" ac-progress ", result["next_required"]["command"])
        self.assertIn("--service-design", result["next_required"]["command"])

    def test_service_design_gate_requires_global_ac_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "checkout.md"
            service_dir = repo / "docs" / "agent-runs" / "run" / "service-designs"
            service_dir.mkdir(parents=True)
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Checkout

                    ## Acceptance Criteria
                    - AC-1 Order is created.
                    - AC-2 Payment is reserved.
                    """
                ).strip(),
                encoding="utf-8",
            )
            (service_dir / "order-service.md").write_text(
                textwrap.dedent(
                    """
                    # Service Design Slice: services/order-service

                    ## Service Scope
                    - Service/module: services/order-service
                    - Allowed edit scope:
                      - services/order-service/

                    ## Global Intent Summary
                    - Create checkout order.

                    ## Mapped Acceptance Criteria
                    | AC | global requirement | service responsibility | local tests |
                    | --- | --- | --- | --- |
                    | AC-1 | Order is created | Persist order | OrderServiceTest |

                    ## Runtime Path
                    - Controller -> OrderService -> Repository

                    ## Service-local TDD Plan
                    - First red test: OrderServiceTest
                    - Expected failure: missing order persistence
                    - Required Maven command: mvn -pl services/order-service -am test

                    ## Dependency Boundary
                    - Independent service change: yes
                    - HTTP/API dependencies: None
                    - MQ/DMQ/Kafka dependencies: None

                    ## Test Impact
                    - mvn -pl services/order-service -am test
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = service_design_gate.validate(repo, design, service_dir)

        self.assertFalse(result["ready"])
        self.assertTrue(any("AC-2" in reason for reason in result["blocked_reasons"]))

    def test_service_design_gate_returns_fix_hints_for_format_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "checkout.md"
            service_dir = repo / "docs" / "agent-runs" / "run" / "service-designs"
            service_dir.mkdir(parents=True)
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Checkout

                    ## Acceptance Criteria
                    - AC-1 Order is created.
                    """
                ).strip(),
                encoding="utf-8",
            )
            (service_dir / "order-service.md").write_text(
                textwrap.dedent(
                    """
                    # Service Design Slice: services/order-service

                    ## Service Scope
                    - Service/module: services/order-service
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = service_design_gate.validate(repo, design, service_dir)

        self.assertFalse(result["ready"])
        hints = result["fix_hints"]
        self.assertTrue(any(hint["action"] == "add_section" and hint["section"] == "Runtime Path" for hint in hints))
        self.assertTrue(any(hint["action"] == "fill_tdd_plan" and "First red test" in hint["template"] for hint in hints))
        self.assertTrue(any(hint["action"] == "close_dependency_boundary" and "Independent service change:" in hint["template"] for hint in hints))

    def test_service_design_gate_allows_complete_service_slices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "checkout.md"
            service_dir = repo / "docs" / "agent-runs" / "run" / "service-designs"
            service_dir.mkdir(parents=True)
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Checkout

                    ## Acceptance Criteria
                    - AC-1 Order is created.
                    - AC-2 Payment is reserved.
                    """
                ).strip(),
                encoding="utf-8",
            )
            for service, ac_id, test_name in (
                ("order-service", "AC-1", "OrderServiceTest"),
                ("payment-service", "AC-2", "PaymentServiceTest"),
            ):
                (service_dir / f"{service}.md").write_text(
                    textwrap.dedent(
                        f"""
                        # Service Design Slice: services/{service}

                        ## Service Scope
                        - Service/module: services/{service}
                        - Allowed edit scope:
                          - services/{service}/

                        ## Global Intent Summary
                        - Checkout service responsibility.

                        ## Mapped Acceptance Criteria
                        | AC | global requirement | service responsibility | local tests |
                        | --- | --- | --- | --- |
                        | {ac_id} | Requirement | Local responsibility | {test_name} |

                        ## Runtime Path
                        - Controller -> Service -> Repository

                        ## Service-local TDD Plan
                        - First red test: {test_name}
                        - Expected failure: missing {service} behavior
                        - Required Maven command: mvn -pl services/{service} -am test

                        ## Dependency Boundary
                        - Independent service change: yes
                        - HTTP/API dependencies: None
                        - MQ/DMQ/Kafka dependencies: None

                        ## Test Impact
                        - mvn -pl services/{service} -am test
                        """
                    ).strip(),
                    encoding="utf-8",
                )

            result = service_design_gate.validate(repo, design, service_dir)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(["AC-1", "AC-2"], result["mapped_acceptance_ids"])

    def test_service_design_gate_blocks_mojibake_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "checkout.md"
            service_dir = repo / "docs" / "agent-runs" / "run" / "service-designs"
            service_dir.mkdir(parents=True)
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Checkout

                    ## Acceptance Criteria
                    - AC-1 Order is created.
                    """
                ).strip(),
                encoding="utf-8",
            )
            (service_dir / "order-service.md").write_text(
                textwrap.dedent(
                    """
                    # Service Design Slice: services/order-service

                    ## Service Scope
                    - Service/module: services/order-service
                    - Allowed edit scope:
                      - services/order-service/
                    - Explicitly out of scope: 鍏朵粬妯″潡

                    ## Global Intent Summary
                    - Create checkout order.

                    ## Mapped Acceptance Criteria
                    | AC | global requirement | service responsibility | local tests |
                    | --- | --- | --- | --- |
                    | AC-1 | Order is created | Persist order | OrderServiceTest |

                    ## Runtime Path
                    - Controller -> OrderService -> Repository

                    ## Service-local TDD Plan
                    - First red test: OrderServiceTest
                    - Expected failure: missing order persistence
                    - Required Maven command: mvn -pl services/order-service -am test

                    ## Dependency Boundary
                    - Independent service change: yes
                    - HTTP/API dependencies: None
                    - MQ/DMQ/Kafka dependencies: None

                    ## Test Impact
                    - mvn -pl services/order-service -am test
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = service_design_gate.validate(repo, design, service_dir)

        self.assertFalse(result["ready"])
        self.assertTrue(any("mojibake" in reason for reason in result["blocked_reasons"]))

    def test_service_design_gate_cli_emits_utf8_json_on_windows_codepage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "checkout.md"
            service_dir = repo / "docs" / "agent-runs" / "run" / "service-designs"
            service_dir.mkdir(parents=True)
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Checkout

                    ## Acceptance Criteria
                    - AC-1 Order is created.
                    """
                ).strip(),
                encoding="utf-8",
            )
            (service_dir / "order-service.md").write_text(
                textwrap.dedent(
                    """
                    # Service Design Slice: services/order-service

                    ## Service Scope
                    - Service/module: services/order-service
                    - Allowed edit scope:
                      - services/order-service/
                    - Explicitly out of scope: 鍏朵粬妯″潡

                    ## Global Intent Summary
                    - Create checkout order.

                    ## Mapped Acceptance Criteria
                    | AC | global requirement | service responsibility | local tests |
                    | --- | --- | --- | --- |
                    | AC-1 | Order is created | Persist order | OrderServiceTest |

                    ## Runtime Path
                    - Controller -> OrderService -> Repository

                    ## Service-local TDD Plan
                    - First red test: OrderServiceTest
                    - Expected failure: missing order persistence
                    - Required Maven command: mvn -pl services/order-service -am test

                    ## Dependency Boundary
                    - Independent service change: yes

                    ## Test Impact
                    - mvn -pl services/order-service -am test
                    """
                ).strip(),
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "cp936"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "service_design_gate.py"),
                    str(repo),
                    "--global-design",
                    str(design),
                    "--service-design-dir",
                    str(service_dir),
                    "--json",
                ],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertNotEqual(0, completed.returncode)
        decoded = completed.stdout.decode("utf-8")
        self.assertIn("mojibake", decoded)

    def test_service_design_command_transitions_multi_run_to_planned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "checkout.md"
            service_dir = repo / "docs" / "agent-runs" / "run" / "service-designs"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            design.parent.mkdir(parents=True)
            service_dir.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Checkout

                    ## Acceptance Criteria
                    - AC-1 Order is created.
                    - AC-2 Payment is reserved.
                    """
                ).strip(),
                encoding="utf-8",
            )
            for service, ac_id, test_name in (
                ("order-service", "AC-1", "OrderServiceTest"),
                ("payment-service", "AC-2", "PaymentServiceTest"),
            ):
                (service_dir / f"{service}.md").write_text(
                    textwrap.dedent(
                        f"""
                        # Service Design Slice: services/{service}

                        ## Service Scope
                        - Service/module: services/{service}
                        - Allowed edit scope:
                          - services/{service}/

                        ## Global Intent Summary
                        - Checkout service responsibility.

                        ## Mapped Acceptance Criteria
                        | AC | global requirement | service responsibility | local tests |
                        | --- | --- | --- | --- |
                        | {ac_id} | Requirement | Local responsibility | {test_name} |

                        ## Runtime Path
                        - Controller -> Service -> Repository

                        ## Service-local TDD Plan
                        - First red test: {test_name}
                        - Expected failure: missing {service} behavior
                        - Required Maven command: mvn -pl services/{service} -am test

                        ## Dependency Boundary
                        - Independent service change: yes
                        - HTTP/API dependencies: None
                        - MQ/DMQ/Kafka dependencies: None

                        ## Test Impact
                        - mvn -pl services/{service} -am test
                        """
                    ).strip(),
                    encoding="utf-8",
                )
            state = run_state.build_state(
                "run",
                "multi",
                ["services/order-service", "services/payment-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "SERVICE_DESIGN_REQUIRED",
            )
            run_state.write_state(repo, state_path, state)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            role_template = Path("docs/agent-runs/run/agent-roles/use-case-designer.md")
            write_role_template(repo, role_template)
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "service-designer-order-service",
                                "phase": "design",
                                "role_group": "design",
                                "service": "services/order-service",
                                "outputs": ["docs/agent-runs/run/service-designs/order-service.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            },
                            {
                                "id": "T02",
                                "agent": "service-designer-payment-service",
                                "phase": "design",
                                "role_group": "design",
                                "service": "services/payment-service",
                                "outputs": ["docs/agent-runs/run/service-designs/payment-service.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            },
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            first = complete_dispatched_task(
                repo,
                schedule_path,
                state_path,
                "T01",
                "service-designer-order-service",
                ["docs/agent-runs/run/service-designs/order-service.md"],
            )
            second = complete_dispatched_task(
                repo,
                schedule_path,
                state_path,
                "T02",
                "service-designer-payment-service",
                ["docs/agent-runs/run/service-designs/payment-service.md"],
            )

            code, result = e2e_dev_harness.service_design(
                SimpleNamespace(
                    repo=repo,
                    global_design=design,
                    service_design_dir=service_dir,
                    service_design=None,
                    emit_template=None,
                    run_state=state_path,
                    status_file=None,
                )
            )
            updated = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(first["ready"], first["blocked_reasons"])
        self.assertTrue(second["ready"], second["blocked_reasons"])
        self.assertEqual(0, code)
        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("PLANNED", updated["lifecycle"])
        self.assertEqual("passed", updated["gates"]["service_design"])

    def test_service_design_command_blocks_without_service_design_worker_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "checkout.md"
            service_dir = repo / "docs" / "agent-runs" / "run" / "service-designs"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            design.parent.mkdir(parents=True)
            service_dir.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Checkout

                    ## Acceptance Criteria
                    - AC-1 Order is created.
                    - AC-2 Payment is reserved.
                    """
                ).strip(),
                encoding="utf-8",
            )
            for service, ac_id, test_name in (
                ("order-service", "AC-1", "OrderServiceTest"),
                ("payment-service", "AC-2", "PaymentServiceTest"),
            ):
                (service_dir / f"{service}.md").write_text(
                    textwrap.dedent(
                        f"""
                        # Service Design Slice: services/{service}

                        ## Service Scope
                        - Service/module: services/{service}
                        - Allowed edit scope:
                          - services/{service}/

                        ## Global Intent Summary
                        - Checkout service responsibility.

                        ## Mapped Acceptance Criteria
                        | AC | global requirement | service responsibility | local tests |
                        | --- | --- | --- | --- |
                        | {ac_id} | Requirement | Local responsibility | {test_name} |

                        ## Runtime Path
                        - Controller -> Service -> Repository

                        ## Service-local TDD Plan
                        - First red test: {test_name}
                        - Expected failure: missing {service} behavior
                        - Required Maven command: mvn -pl services/{service} -am test

                        ## Dependency Boundary
                        - Independent service change: yes
                        - HTTP/API dependencies: None
                        - MQ/DMQ/Kafka dependencies: None

                        ## Test Impact
                        - mvn -pl services/{service} -am test
                        """
                    ).strip(),
                    encoding="utf-8",
                )
            state = run_state.build_state(
                "run",
                "multi",
                ["services/order-service", "services/payment-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "SERVICE_DESIGN_REQUIRED",
            )
            run_state.write_state(repo, state_path, state)

            code, result = e2e_dev_harness.service_design(
                SimpleNamespace(
                    repo=repo,
                    global_design=design,
                    service_design_dir=service_dir,
                    service_design=None,
                    emit_template=None,
                    run_state=state_path,
                    status_file=None,
                )
            )
            updated = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])
        self.assertEqual("SERVICE_DESIGN_REQUIRED", updated["lifecycle"])
        self.assertTrue(any("service-design" in reason and "dispatch" in reason for reason in result["blocked_reasons"]))

    def test_service_design_emit_template_writes_gate_aligned_starter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "checkout.md"
            service_dir = repo / "docs" / "agent-runs" / "run" / "service-designs"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Checkout

                    ## Acceptance Criteria
                    - AC-1 Order is created.
                    """
                ).strip(),
                encoding="utf-8",
            )

            _code, result = e2e_dev_harness.service_design(
                SimpleNamespace(
                    repo=repo,
                    global_design=design,
                    service_design_dir=service_dir,
                    service_design=None,
                    emit_template=["services/payment-service"],
                    run_state=None,
                    status_file=None,
                )
            )
            written = repo / result["templates_written"][0]
            written_exists = written.exists()
            text = written.read_text(encoding="utf-8")

        self.assertTrue(written_exists)
        self.assertIn("## Runtime Path", text)
        self.assertIn("## Local Sequence", text)
        self.assertIn("sequenceDiagram", text)
        self.assertIn("## Service-local TDD Plan", text)
        self.assertIn("First red test:", text)
        self.assertIn("Expected failure:", text)
        self.assertIn("Required Maven command:", text)
        self.assertIn("Independent service change:", text)

    def test_service_design_gate_requires_local_sequence_for_cross_service_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "checkout.md"
            service_dir = repo / "docs" / "agent-runs" / "run" / "service-designs"
            service_dir.mkdir(parents=True)
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Checkout

                    ## Acceptance Criteria
                    - AC-1 Order publishes payment reserve event.
                    """
                ).strip(),
                encoding="utf-8",
            )
            (service_dir / "order-service.md").write_text(
                textwrap.dedent(
                    """
                    # Service Design Slice: services/order-service

                    ## Service Scope
                    - Service/module: services/order-service
                    - Allowed edit scope:
                      - services/order-service/

                    ## Global Intent Summary
                    - Publish payment reserve event.

                    ## Mapped Acceptance Criteria
                    | AC | global requirement | service responsibility | local tests |
                    | --- | --- | --- | --- |
                    | AC-1 | Publish payment reserve event | Send event after order creation | OrderServiceTest |

                    ## Runtime Path
                    - Controller -> OrderService -> RocketMQ sender

                    ## Service-local TDD Plan
                    - First red test: OrderServiceTest
                    - Expected failure: missing event publish
                    - Required Maven command: mvn -pl services/order-service -am test

                    ## Dependency Boundary
                    - Independent service change: no, publishes MQ event consumed by payment-service
                    - HTTP/API dependencies: None
                    - MQ/DMQ/Kafka dependencies: topic payment.reserve, consumer payment-service

                    ## Test Impact
                    - mvn -pl services/order-service -am test
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = service_design_gate.validate(repo, design, service_dir)

        self.assertFalse(result["ready"])
        self.assertTrue(any("Local Sequence" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any(hint["action"] == "add_local_sequence" for hint in result["fix_hints"]))

    def test_multi_implementation_gate_blocks_before_service_design_state_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifacts = orchestration_plan.artifacts(
                "checkout",
                agent_run_dir="docs/agent-runs/run",
                services=["services/order-service", "services/payment-service"],
            )
            design = repo / "docs" / "design" / "checkout.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Checkout

                    ## Restated Intent
                    Build checkout.

                    ## Acceptance Criteria
                    - AC-1 Order is created.
                    - AC-2 Payment is reserved.

                    ## Open Questions
                    None
                    """
                ).strip(),
                encoding="utf-8",
            )
            artifacts["design_doc"] = "docs/design/checkout.md"
            e2e_dev_harness.create_handoff_files(repo, artifacts)
            schedule = orchestration_plan.agent_schedule(
                "multi",
                ["services/order-service", "services/payment-service"],
                orchestration_plan.agent_plan("multi", artifacts, ["services/order-service", "services/payment-service"]),
            )
            (repo / artifacts["agent_schedule"]).write_text(json.dumps(schedule, indent=2), encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "docs/agent-runs/run",
                artifacts,
                "multi",
                ["services/order-service", "services/payment-service"],
            )
            artifact_registry.write_registry(repo, repo / artifacts["artifact_registry"], registry)
            state_path = repo / artifacts["run_state"]
            state = run_state.build_state(
                "docs/agent-runs/run",
                "multi",
                ["services/order-service", "services/payment-service"],
                artifacts["artifact_registry"],
                "SERVICE_DESIGN_REQUIRED",
            )
            run_state.write_state(repo, state_path, state)

            result = implementation_gate.validate_gate_request(
                implementation_gate.GateRequest(
                    repo=repo,
                    phase="implementation",
                    design_doc=Path("docs/design/checkout.md"),
                    run_state=Path(artifacts["run_state"]),
                )
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("service-design gate transitions" in reason for reason in result["blocked_reasons"]))

    def test_multi_implementation_gate_waits_for_tdd_and_r2_not_code_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            services = ["services/order-service", "services/payment-service"]
            artifacts = orchestration_plan.artifacts("checkout", agent_run_dir="docs/agent-runs/run", services=services)
            artifacts["design_doc"] = "docs/design/checkout.md"
            design = repo / artifacts["design_doc"]
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Checkout

                    ## Restated Intent
                    Build checkout.

                    ## Acceptance Criteria
                    - AC-1 Order is created.
                    - AC-2 Payment is reserved.

                    ## Open Questions
                    None
                    """
                ).strip(),
                encoding="utf-8",
            )
            e2e_dev_harness.create_handoff_files(repo, artifacts)
            for service, ac_id, test_name in (
                ("order-service", "AC-1", "OrderServiceTest"),
                ("payment-service", "AC-2", "PaymentServiceTest"),
            ):
                service_design = repo / "docs" / "agent-runs" / "run" / "service-designs" / f"{service}.md"
                service_design.write_text(
                    textwrap.dedent(
                        f"""
                        # Service Design Slice: services/{service}

                        ## Service Scope
                        - Service/module: services/{service}
                        - Allowed edit scope:
                          - services/{service}/

                        ## Global Intent Summary
                        - Checkout service responsibility.

                        ## Mapped Acceptance Criteria
                        | AC | global requirement | service responsibility | local tests |
                        | --- | --- | --- | --- |
                        | {ac_id} | Requirement | Local responsibility | {test_name} |

                        ## Runtime Path
                        - Controller -> Service -> Repository

                        ## Service-local TDD Plan
                        - First red test: {test_name}
                        - Expected failure: missing {service} behavior
                        - Required Maven command: mvn -pl services/{service} -am test

                        ## Dependency Boundary
                        - Independent service change: yes
                        - HTTP/API dependencies: None
                        - MQ/DMQ/Kafka dependencies: None

                        ## Test Impact
                        - mvn -pl services/{service} -am test
                        """
                    ).strip(),
                    encoding="utf-8",
                )
            agents = orchestration_plan.agent_plan("multi", artifacts, services)
            schedule = orchestration_plan.agent_schedule("multi", services, agents)
            (repo / artifacts["agent_schedule"]).write_text(json.dumps(schedule, indent=2), encoding="utf-8")
            registry = artifact_registry.build_registry(repo, "docs/agent-runs/run", artifacts, "multi", services)
            artifact_registry.write_registry(repo, repo / artifacts["artifact_registry"], registry)
            state_path = repo / artifacts["run_state"]
            state = run_state.build_state("docs/agent-runs/run", "multi", services, artifacts["artifact_registry"], "PLANNED")
            state["gates"]["service_design"] = "passed"
            run_state.write_state(repo, state_path, state)

            result = implementation_gate.validate_gate_request(
                implementation_gate.GateRequest(
                    repo=repo,
                    phase="implementation",
                    design_doc=Path(artifacts["design_doc"]),
                    run_state=Path(artifacts["run_state"]),
                )
            )

        self.assertFalse(result["ready"])
        self.assertFalse(any("must be claimed" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("tdd-red" in reason and "r2-review" in reason for reason in result["blocked_reasons"]))

    def test_multi_implementation_gate_requires_dispatch_events_for_tdd_and_r2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            services = ["services/order-service", "services/payment-service"]
            artifacts = orchestration_plan.artifacts("checkout", agent_run_dir="docs/agent-runs/run", services=services)
            artifacts["design_doc"] = "docs/design/checkout.md"
            design = repo / artifacts["design_doc"]
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Checkout

                    ## Restated Intent
                    Build checkout.

                    ## Acceptance Criteria
                    - AC-1 Order is created.
                    - AC-2 Payment is reserved.
                    """
                ).strip(),
                encoding="utf-8",
            )
            e2e_dev_harness.create_handoff_files(repo, artifacts)
            for service, ac_id, test_name in (
                ("order-service", "AC-1", "OrderServiceTest"),
                ("payment-service", "AC-2", "PaymentServiceTest"),
            ):
                service_design = repo / "docs" / "agent-runs" / "run" / "service-designs" / f"{service}.md"
                service_design.write_text(
                    textwrap.dedent(
                        f"""
                        # Service Design Slice: services/{service}

                        ## Service Scope
                        - Service/module: services/{service}
                        - Allowed edit scope:
                          - services/{service}/

                        ## Global Intent Summary
                        - Checkout service responsibility.

                        ## Mapped Acceptance Criteria
                        | AC | global requirement | service responsibility | local tests |
                        | --- | --- | --- | --- |
                        | {ac_id} | Requirement | Local responsibility | {test_name} |

                        ## Runtime Path
                        - Controller -> Service -> Repository

                        ## Service-local TDD Plan
                        - First red test: {test_name}
                        - Expected failure: missing {service} behavior
                        - Required Maven command: mvn -pl services/{service} -am test

                        ## Dependency Boundary
                        - Independent service change: yes
                        - HTTP/API dependencies: None
                        - MQ/DMQ/Kafka dependencies: None

                        ## Test Impact
                        - mvn -pl services/{service} -am test
                        """
                    ).strip(),
                    encoding="utf-8",
                )
            schedule = orchestration_plan.agent_schedule("multi", services, orchestration_plan.agent_plan("multi", artifacts, services))
            for task in schedule["tasks"]:
                if task["phase"] in {"tdd-red", "r2-review"}:
                    task["status"] = "completed"
                if task["phase"] == "implement":
                    task["status"] = "planned"
            (repo / artifacts["agent_schedule"]).write_text(json.dumps(schedule, indent=2), encoding="utf-8")
            registry = artifact_registry.build_registry(repo, "docs/agent-runs/run", artifacts, "multi", services)
            artifact_registry.write_registry(repo, repo / artifacts["artifact_registry"], registry)
            state = run_state.build_state("docs/agent-runs/run", "multi", services, artifacts["artifact_registry"], "PLANNED")
            state["gates"]["service_design"] = "passed"

            result = implementation_gate.validate_multi_service_preconditions(
                repo,
                implementation_gate.GateRequest(repo=repo, phase="implementation", design_doc=Path(artifacts["design_doc"])),
                state,
                registry,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("dispatch-complete" in reason and "worker_completed" in reason for reason in result["blocked_reasons"]))

    def test_multi_completion_gate_requires_dispatch_events_for_completed_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            services = ["services/order-service"]
            artifacts = orchestration_plan.artifacts("checkout", agent_run_dir="docs/agent-runs/run", services=services)
            artifacts["design_doc"] = "docs/design/checkout.md"
            design = repo / artifacts["design_doc"]
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Checkout

                    ## Restated Intent
                    Build checkout.

                    ## Acceptance Criteria
                    - AC-1 Order is created.
                    """
                ).strip(),
                encoding="utf-8",
            )
            e2e_dev_harness.create_handoff_files(repo, artifacts)
            service_design = repo / "docs" / "agent-runs" / "run" / "service-designs" / "order-service.md"
            service_design.write_text(
                textwrap.dedent(
                    """
                    # Service Design Slice: services/order-service

                    ## Service Scope
                    - Service/module: services/order-service
                    - Allowed edit scope:
                      - services/order-service/

                    ## Global Intent Summary
                    - Checkout service responsibility.

                    ## Mapped Acceptance Criteria
                    | AC | global requirement | service responsibility | local tests |
                    | --- | --- | --- | --- |
                    | AC-1 | Requirement | Local responsibility | OrderServiceTest |

                    ## Runtime Path
                    - Controller -> Service -> Repository

                    ## Service-local TDD Plan
                    - First red test: OrderServiceTest
                    - Expected failure: missing order behavior
                    - Required Maven command: mvn -pl services/order-service -am test

                    ## Dependency Boundary
                    - Independent service change: yes
                    - HTTP/API dependencies: None
                    - MQ/DMQ/Kafka dependencies: None

                    ## Test Impact
                    - mvn -pl services/order-service -am test
                    """
                ).strip(),
                encoding="utf-8",
            )
            schedule = orchestration_plan.agent_schedule("multi", services, orchestration_plan.agent_plan("multi", artifacts, services))
            for task in schedule["tasks"]:
                task["status"] = "completed"
            (repo / artifacts["agent_schedule"]).write_text(json.dumps(schedule, indent=2), encoding="utf-8")
            registry = artifact_registry.build_registry(repo, "docs/agent-runs/run", artifacts, "multi", services)
            artifact_registry.write_registry(repo, repo / artifacts["artifact_registry"], registry)
            state = run_state.build_state("docs/agent-runs/run", "multi", services, artifacts["artifact_registry"], "IMPLEMENTED")
            state["gates"]["service_design"] = "passed"

            result = implementation_gate.validate_multi_service_preconditions(
                repo,
                implementation_gate.GateRequest(repo=repo, phase="completion", design_doc=Path(artifacts["design_doc"])),
                state,
                registry,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("dispatch-complete" in reason and "worker_completed" in reason for reason in result["blocked_reasons"]))

    def test_service_plan_archive_contains_microservice_scoped_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifacts = orchestration_plan.artifacts(
                "checkout",
                run_date="2026-05-23",
                services=["services/order-service"],
            )

            e2e_dev_harness.create_handoff_files(repo, artifacts)

            service_plan = repo / artifacts["service_plans"]["services/order-service"]["service_plan"]
            service_design = repo / artifacts["service_plans"]["services/order-service"]["service_design"]
            text = service_plan.read_text(encoding="utf-8")
            design_text = service_design.read_text(encoding="utf-8")
            request_text = (repo / artifacts["implementation_review_request"]).read_text(encoding="utf-8")

        self.assertIn("# Service Design Slice: services/order-service", design_text)
        self.assertIn("## Mapped Acceptance Criteria", design_text)
        self.assertIn("## Dependency Boundary", design_text)
        self.assertIn("# Service Implementation Plan: services/order-service", text)
        self.assertIn("## Agent Assignment", text)
        self.assertIn("## Modification Points", text)
        self.assertIn("## Change Logic", text)
        self.assertIn("## Service-local TDD Plan", text)
        self.assertIn("## Implementation Manifest", text)
        self.assertIn("## Cross-service Contracts", text)
        self.assertIn("Reviewer Agent:", request_text)
        self.assertIn("Forbidden:", request_text)
        self.assertIn("Output:", request_text)

    def test_artifact_registry_detects_stale_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifact = repo / "docs" / "agent-runs" / "run" / "exec-plan.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("initial\n", encoding="utf-8")
            artifacts = {"exec_plan": "docs/agent-runs/run/exec-plan.md"}
            registry = artifact_registry.build_registry(repo, "run", artifacts, "single", [])
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            artifact_registry.write_registry(repo, registry_path, registry)
            artifact.write_text("changed\n", encoding="utf-8")

            result = artifact_registry.validate_registry(repo, registry_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("stale" in reason.lower() for reason in result["blocked_reasons"]))

    def test_artifact_registry_refresh_updates_status_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifact = repo / "docs" / "agent-runs" / "run" / "exec-plan.md"
            artifact.parent.mkdir(parents=True)
            registry = artifact_registry.build_registry(
                repo,
                "run",
                {"exec_plan": "docs/agent-runs/run/exec-plan.md"},
                "single",
                [],
            )
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            artifact_registry.write_registry(repo, registry_path, registry)
            artifact.write_text("plan\n", encoding="utf-8")

            result = artifact_registry.refresh_registry(repo, registry_path)
            refreshed = json.loads(registry_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(["global:exec_plan"], result["changed"])
        self.assertEqual("present", refreshed["artifacts"][0]["status"])
        self.assertTrue(refreshed["artifacts"][0]["sha256"])

    def test_artifact_registry_blocks_paths_outside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            registry_path.parent.mkdir(parents=True)
            registry_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.artifact-registry.v1",
                        "artifacts": [
                            {
                                "type": "exec_plan",
                                "path": "../outside.md",
                                "kind": "file",
                                "required_by_completion": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = artifact_registry.validate_registry(repo, registry_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("outside repository" in reason for reason in result["blocked_reasons"]))

    def test_artifact_registry_strict_blocks_missing_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifact = repo / "docs" / "agent-runs" / "run" / "exec-plan.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("plan\n", encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "run",
                {"exec_plan": "docs/agent-runs/run/exec-plan.md"},
                "single",
                [],
            )
            registry["artifacts"][0]["sha256"] = ""
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            artifact_registry.write_registry(repo, registry_path, registry)

            result = artifact_registry.validate_registry(repo, registry_path, strict=True)

        self.assertFalse(result["ready"])
        self.assertTrue(any("missing" in reason.lower() for reason in result["blocked_reasons"]))

    def test_run_state_validates_artifact_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifact = repo / "docs" / "agent-runs" / "run" / "exec-plan.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("plan\n", encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "run",
                {"exec_plan": "docs/agent-runs/run/exec-plan.md"},
                "single",
                [],
            )
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            artifact_registry.write_registry(repo, registry_path, registry)
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json")
            run_state.write_state(repo, state_path, state)

            result = run_state.validate_state(repo, state_path)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("PLANNED", result["lifecycle"])

    def test_run_state_transition_records_history_and_gate_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            evidence = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-gate.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red-test.txt"
            evidence.parent.mkdir(parents=True)
            red.write_text("expected failure\n", encoding="utf-8")
            evidence.write_text(json.dumps(implementation_gate_payload(red)), encoding="utf-8")
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json")
            run_state.write_state(repo, state_path, state)

            result = run_state.transition_state(
                repo,
                state_path,
                "IMPLEMENTED",
                gate="implementation",
                gate_status="passed",
                evidence=evidence,
            )
            updated = json.loads(state_path.read_text(encoding="utf-8"))
            lock_exists = (state_path.parent / ".phase-lock").exists()
            summary_path = state_path.parent / "coordinator-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("IMPLEMENTED", updated["lifecycle"])
        self.assertEqual("passed", updated["gates"]["implementation"])
        self.assertEqual("PLANNED", updated["history"][0]["from"])
        self.assertEqual("IMPLEMENTED", updated["history"][0]["to"])
        self.assertTrue(lock_exists)
        self.assertEqual("IMPLEMENTED", summary["lifecycle"])
        self.assertEqual(str(state_path), summary["artifact_pointers"]["run_state"])
        self.assertEqual("phase-transition", summary["next_action"]["orchestration_action"])

    def test_run_state_transition_blocks_regression_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "VERIFIED")
            run_state.write_state(repo, state_path, state)

            result = run_state.transition_state(repo, state_path, "PLANNED")

        self.assertFalse(result["ready"])
        self.assertTrue(any("regression" in reason.lower() for reason in result["blocked_reasons"]))

    def test_run_state_transition_blocks_skip_not_in_transition_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)

            result = run_state.transition_state(repo, state_path, "VERIFIED")

        self.assertFalse(result["ready"])
        self.assertTrue(any("transition table" in reason for reason in result["blocked_reasons"]))

    def test_run_state_transition_blocks_waiting_dispatch_as_main_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = run_state.transition_state(repo, state_path, "WAITING_DISPATCH")

        self.assertFalse(result["ready"])
        self.assertTrue(any("transition table" in reason for reason in result["blocked_reasons"]))

    def test_run_state_blocks_manual_implemented_transition_without_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = run_state.transition_state(repo, state_path, "IMPLEMENTED")

        self.assertFalse(result["ready"])
        self.assertTrue(any("gate=implementation" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("requires implementation gate evidence" in reason for reason in result["blocked_reasons"]))

    def test_run_state_blocks_implemented_transition_with_non_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            evidence = repo / "docs" / "agent-runs" / "run" / "evidence" / "red-test.txt"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("expected failure\n", encoding="utf-8")
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = run_state.transition_state(
                repo,
                state_path,
                "IMPLEMENTED",
                gate="implementation",
                gate_status="passed",
                evidence=evidence,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("valid JSON" in reason or "implementation gate" in reason for reason in result["blocked_reasons"]))

    def test_run_state_blocks_forged_ready_only_implementation_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            evidence = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-gate.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(json.dumps({"phase": "implementation", "ready": True}), encoding="utf-8")
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = run_state.transition_state(
                repo,
                state_path,
                "IMPLEMENTED",
                gate="implementation",
                gate_status="passed",
                evidence=evidence,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("TDD red" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("semantic reviews" in reason for reason in result["blocked_reasons"]))

    def test_run_state_blocks_verified_transition_without_completion_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            implementation_gate = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-gate.json"
            unit_evidence = repo / "docs" / "agent-runs" / "run" / "evidence" / "unit-test.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red-test.txt"
            implementation_gate.parent.mkdir(parents=True)
            red.write_text("expected failure\n", encoding="utf-8")
            implementation_gate.write_text(json.dumps(implementation_gate_payload(red)), encoding="utf-8")
            unit_evidence.write_text(json.dumps({"command": "mvn test", "exit_code": 0}), encoding="utf-8")
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)
            implemented = run_state.transition_state(
                repo,
                state_path,
                "IMPLEMENTED",
                gate="implementation",
                gate_status="passed",
                evidence=implementation_gate,
            )

            result = run_state.transition_state(
                repo,
                state_path,
                "VERIFIED",
                gate="completion",
                gate_status="passed",
                evidence=unit_evidence,
            )

        self.assertTrue(implemented["ready"], implemented["blocked_reasons"])
        self.assertFalse(result["ready"])
        self.assertTrue(any("completion gate evidence" in reason for reason in result["blocked_reasons"]))

    def test_run_state_allows_verified_transition_with_completion_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            implementation_gate = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-gate.json"
            completion_gate = repo / "docs" / "agent-runs" / "run" / "evidence" / "completion-gate.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red-test.txt"
            implementation_gate.parent.mkdir(parents=True)
            red.write_text("expected failure\n", encoding="utf-8")
            implementation_gate.write_text(json.dumps(implementation_gate_payload(red)), encoding="utf-8")
            completion_gate.write_text(json.dumps({"phase": "completion", "ready": True}), encoding="utf-8")
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)
            implemented = run_state.transition_state(
                repo,
                state_path,
                "IMPLEMENTED",
                gate="implementation",
                gate_status="passed",
                evidence=implementation_gate,
            )

            result = run_state.transition_state(
                repo,
                state_path,
                "VERIFIED",
                gate="completion",
                gate_status="passed",
                evidence=completion_gate,
            )

        self.assertTrue(implemented["ready"], implemented["blocked_reasons"])
        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("VERIFIED", result["lifecycle"])

    def test_multi_phase_guard_requires_claimed_service_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            state = run_state.build_state(
                "run",
                "multi",
                ["services/order-service", "services/payment-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            state["gates"]["service_design"] = "passed"
            write_implemented_state(repo, state_path, state)
            schedule = {
                "schema": "e2e-dev-harness.agent-schedule.v1",
                "selected_mode": "multi",
                "services": ["services/order-service", "services/payment-service"],
                "tasks": [
                    {
                        "id": "T01",
                        "agent": "code-developer-order-service",
                        "phase": "implement",
                        "service": "services/order-service",
                        "status": "planned",
                    }
                ],
            }
            schedule_path.parent.mkdir(parents=True, exist_ok=True)
            schedule_path.write_text(json.dumps(schedule, indent=2), encoding="utf-8")

            blocked = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/order-service/src/main/java/OrderService.java")],
                run_dir=Path("docs/agent-runs/run"),
            )
            claim = agent_scheduler.claim(repo, schedule_path, "T01", "agent-order", state_path)
            claimed_state = json.loads(state_path.read_text(encoding="utf-8"))
            claimed_state["dispatches"] = {
                "T01": {
                    "status": "worker_running",
                    "current_task_id": "T01",
                    "current_agent": "code-developer-order-service",
                    "worker_handle": "code-worker-order",
                }
            }
            claimed_state["dispatch"] = claimed_state["dispatches"]["T01"]
            run_state.write_state(repo, state_path, claimed_state)
            allowed = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/order-service/src/main/java/OrderService.java")],
                run_dir=Path("docs/agent-runs/run"),
            )
            cross_service = phase_guard.validate_action(
                repo,
                "Edit",
                [
                    Path("services/order-service/src/main/java/OrderService.java"),
                    Path("services/payment-service/src/main/java/PaymentService.java"),
                ],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(blocked["ready"])
        self.assertTrue(any("no claimed code-developer task" in reason for reason in blocked["blocked_reasons"]))
        self.assertTrue(claim["ready"], claim["blocked_reasons"])
        self.assertTrue(allowed["ready"], allowed["blocked_reasons"])
        self.assertFalse(cross_service["ready"])
        self.assertTrue(any("only one service" in reason for reason in cross_service["blocked_reasons"]))

    def test_multi_phase_guard_blocks_unscoped_shared_runtime_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "run",
                "multi",
                ["services/order-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            state["owners"]["services/order-service"] = {
                "task_id": "T01",
                "agent": "agent-order",
                "status": "claimed",
            }
            write_implemented_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("pom.xml")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("outside claimed services" in reason for reason in result["blocked_reasons"]))

    def test_multi_phase_guard_allows_explicit_shared_edit_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "run",
                "multi",
                ["services/order-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            state["owners"]["services/order-service"] = {
                "task_id": "T01",
                "agent": "agent-order",
                "status": "claimed",
            }
            state["shared_edit_scopes"] = ["shared-kernel"]
            state["dispatches"] = {
                "T01": {
                    "status": "worker_running",
                    "current_task_id": "T01",
                    "current_agent": "code-developer-order-service",
                    "worker_handle": "code-worker-order",
                }
            }
            state["dispatch"] = state["dispatches"]["T01"]
            write_implemented_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("shared-kernel/src/main/java/com/example/Money.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_multi_phase_guard_blocks_merged_shared_scope_without_merged_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "run",
                "multi",
                ["jeepay-payment"],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            state["owners"]["jeepay-payment"] = {
                "task_id": "T01",
                "agent": "agent-payment",
                "status": "claimed",
            }
            state["shared_edit_scopes"] = ["jeepay-core/"]
            state["shared_edit_scope_owners"] = {"jeepay-core/": "merged-modules"}
            state["dispatches"] = {
                "T01": {
                    "status": "worker_running",
                    "current_task_id": "T01",
                    "current_agent": "code-developer-jeepay-payment",
                    "worker_handle": "code-worker-payment",
                }
            }
            state["dispatch"] = state["dispatches"]["T01"]
            write_implemented_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("jeepay-core/src/main/java/com/example/Core.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("merged-modules" in reason for reason in result["blocked_reasons"]))

    def test_agent_task_complete_requires_existing_declared_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            evidence = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service" / "unit-test-evidence.txt"
            other = repo / "docs" / "agent-runs" / "run" / "evidence" / "other.txt"
            evidence.parent.mkdir(parents=True)
            other.parent.mkdir(parents=True)
            evidence.write_text("passed\n", encoding="utf-8")
            other.write_text("passed\n", encoding="utf-8")
            schedule = {
                "schema": "e2e-dev-harness.agent-schedule.v1",
                "selected_mode": "multi",
                "services": ["services/order-service"],
                "tasks": [
                    {
                        "id": "T01",
                        "agent": "code-developer-order-service",
                        "phase": "implement",
                        "service": "services/order-service",
                        "status": "claimed",
                        "owner": "agent-order",
                        "outputs": [
                            "docs/agent-runs/run/service-plans/order-service/unit-test-evidence.txt"
                        ],
                    }
                ],
            }
            schedule_path.parent.mkdir(parents=True, exist_ok=True)
            schedule_path.write_text(json.dumps(schedule, indent=2), encoding="utf-8")

            missing = agent_scheduler.complete(repo, schedule_path, "T01", "agent-order", evidence=["missing.txt"])
            wrong = agent_scheduler.complete(repo, schedule_path, "T01", "agent-order", evidence=[str(other.relative_to(repo))])
            ok = agent_scheduler.complete(repo, schedule_path, "T01", "agent-order", evidence=[str(evidence.relative_to(repo))])

        self.assertFalse(missing["ready"])
        self.assertTrue(any("missing" in reason for reason in missing["blocked_reasons"]))
        self.assertFalse(wrong["ready"])
        self.assertTrue(any("task outputs" in reason for reason in wrong["blocked_reasons"]))
        self.assertTrue(ok["ready"], ok["blocked_reasons"])
        self.assertEqual(["docs/agent-runs/run/service-plans/order-service/unit-test-evidence.txt"], ok["task"]["evidence"])

    def test_agent_task_claim_blocks_unfinished_dependency_phases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            schedule_path.parent.mkdir(parents=True)
            state = run_state.build_state("run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            state["gates"]["service_design"] = "passed"
            run_state.write_state(repo, state_path, state)
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {"id": "T01", "phase": "tdd-red", "status": "completed"},
                            {"id": "T02", "phase": "r2-review", "status": "planned"},
                            {
                                "id": "T03",
                                "phase": "implement",
                                "service": "services/order-service",
                                "status": "planned",
                                "depends_on_phases": ["tdd-red", "r2-review"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = agent_scheduler.claim(repo, schedule_path, "T03", "agent-order", state_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("r2-review" in reason for reason in result["blocked_reasons"]))

    def test_agent_task_complete_r2_transitions_planned_to_red_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            evidence = repo / "docs" / "agent-runs" / "run" / "reviews" / "R2-test-review.md"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("# R2\n\nStatus: approved\n", encoding="utf-8")
            state = run_state.build_state("run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            state["gates"]["service_design"] = "passed"
            run_state.write_state(repo, state_path, state)
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {"id": "T01", "phase": "tdd-red", "status": "completed"},
                            {
                                "id": "T02",
                                "phase": "r2-review",
                                "agent": "test-reviewer",
                                "status": "claimed",
                                "owner": "test-reviewer",
                                "outputs": ["docs/agent-runs/run/reviews/R2-test-review.md"],
                            },
                            {
                                "id": "T03",
                                "phase": "implement",
                                "service": "services/order-service",
                                "status": "planned",
                                "depends_on_phases": ["tdd-red", "r2-review"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = agent_scheduler.complete(
                repo,
                schedule_path,
                "T02",
                "test-reviewer",
                state_path,
                evidence=["docs/agent-runs/run/reviews/R2-test-review.md"],
            )
            updated = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("RED_READY", updated["lifecycle"])
        self.assertEqual("RED_READY", result["run_state_transition"]["lifecycle"])

    def test_agent_task_complete_blocks_strict_schedule_without_dispatch_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            evidence = repo / "docs" / "agent-runs" / "run" / "reviews" / "R2-test-review.md"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("# R2\n\nStatus: approved\n", encoding="utf-8")
            state = run_state.build_state("run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "tasks": [
                            {"id": "T01", "phase": "tdd-red", "status": "completed"},
                            {
                                "id": "T02",
                                "phase": "r2-review",
                                "agent": "test-reviewer",
                                "status": "claimed",
                                "owner": "test-reviewer",
                                "outputs": ["docs/agent-runs/run/reviews/R2-test-review.md"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = agent_scheduler.complete(
                repo,
                schedule_path,
                "T02",
                "test-reviewer",
                state_path,
                evidence=["docs/agent-runs/run/reviews/R2-test-review.md"],
            )
            updated = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertFalse(result["ready"])
        self.assertTrue(any("dispatch-complete" in reason for reason in result["blocked_reasons"]))
        self.assertEqual("PLANNED", updated["lifecycle"])

    def test_agent_task_allow_local_completion_records_recovery_event_without_completing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            evidence = repo / "docs" / "agent-runs" / "run" / "reviews" / "R2-test-review.md"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("# R2\n\nStatus: approved\n", encoding="utf-8")
            state = run_state.build_state("run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "tasks": [
                            {"id": "T01", "phase": "tdd-red", "status": "completed"},
                            {
                                "id": "T02",
                                "phase": "r2-review",
                                "agent": "test-reviewer",
                                "status": "claimed",
                                "owner": "test-reviewer",
                                "outputs": ["docs/agent-runs/run/reviews/R2-test-review.md"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = agent_scheduler.complete(
                repo,
                schedule_path,
                "T02",
                "test-reviewer",
                state_path,
                evidence=["docs/agent-runs/run/reviews/R2-test-review.md"],
                allow_local_completion=True,
            )
            updated_schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
            code, next_result = e2e_dev_harness.next_step(
                SimpleNamespace(repo=repo, state=state_path, runtime="codex", status_file=None)
            )
            summary = json.loads(Path(next_result["coordinator_summary_path"]).read_text(encoding="utf-8"))

        self.assertFalse(result["ready"])
        self.assertTrue(any("dispatch-complete --manual-recovery" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("local completion" in warning.lower() for warning in result["warnings"]))
        self.assertTrue(updated_schedule["manual_recovery_events"])
        self.assertEqual("claimed", updated_schedule["tasks"][1]["status"])
        self.assertEqual(0, code)
        self.assertTrue(summary["manual_recovery_events"])

    def test_dispatch_complete_manual_recovery_requires_approval_before_closing_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            evidence = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service" / "unit-test-evidence.txt"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("passed\n", encoding="utf-8")
            state = run_state.build_state("run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED")
            state["dispatch"] = {
                "status": "worker_running",
                "current_task_id": "T03",
                "current_agent": "code-developer-order-service",
                "worker_handle": "fresh-worker-T03",
                "worker_session": "fresh-worker-session-T03",
                "spawn_acknowledged_at": "2026-06-03T14:44:24Z",
                "spawn_confirmed_by": "dispatch_ack",
            }
            state["dispatches"] = {"T03": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "tasks": [
                            {"id": "T01", "phase": "tdd-red", "status": "completed"},
                            {
                                "id": "T03",
                                "phase": "implement",
                                "agent": "code-developer-order-service",
                                "service": "services/order-service",
                                "status": "claimed",
                                "owner": "code-developer-order-service",
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/unit-test-evidence.txt"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            code, result = e2e_dev_harness.dispatch_complete(
                SimpleNamespace(
                    repo=repo,
                    schedule=schedule_path,
                    state=state_path,
                    task_id="T03",
                    agent="code-developer-order-service",
                    evidence=["docs/agent-runs/run/service-plans/order-service/unit-test-evidence.txt"],
                    manual_recovery=True,
                    recovery_approval=None,
                    status_file=None,
                )
            )
            updated_schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
            updated_state = json.loads(state_path.read_text(encoding="utf-8"))
            event_path = state_path.parent / "dispatch-events" / "T03-completed.json"

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])
        self.assertTrue(
            any("recovery" in reason.lower() and "approval" in reason.lower() for reason in result["blocked_reasons"]),
            result["blocked_reasons"],
        )
        self.assertEqual("claimed", updated_schedule["tasks"][1]["status"])
        self.assertEqual("worker_running", updated_state["dispatches"]["T03"]["status"])
        self.assertFalse(event_path.exists())

    def test_dispatch_complete_manual_recovery_blocks_without_active_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            evidence = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service" / "unit-test-evidence.txt"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("passed\n", encoding="utf-8")
            state = run_state.build_state("run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED")
            run_state.write_state(repo, state_path, state)
            schedule_path.parent.mkdir(parents=True, exist_ok=True)
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "tasks": [
                            {
                                "id": "T03",
                                "phase": "implement",
                                "agent": "code-developer-order-service",
                                "service": "services/order-service",
                                "status": "claimed",
                                "owner": "code-developer-order-service",
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/unit-test-evidence.txt"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            code, result = e2e_dev_harness.dispatch_complete(
                SimpleNamespace(
                    repo=repo,
                    schedule=schedule_path,
                    state=state_path,
                    task_id="T03",
                    agent="code-developer-order-service",
                    evidence=["docs/agent-runs/run/service-plans/order-service/unit-test-evidence.txt"],
                    manual_recovery=True,
                    recovery_approval=None,
                    status_file=None,
                )
            )
            updated_schedule = json.loads(schedule_path.read_text(encoding="utf-8"))

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])
        self.assertTrue(any("active dispatch" in reason.lower() for reason in result["blocked_reasons"]))
        self.assertEqual("claimed", updated_schedule["tasks"][0]["status"])

    def test_dispatch_complete_manual_recovery_with_approval_closes_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            evidence = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service" / "unit-test-evidence.txt"
            approval = repo / "docs" / "agent-runs" / "run" / "recovery-requests" / "T03-approved.json"
            evidence.parent.mkdir(parents=True)
            approval.parent.mkdir(parents=True)
            evidence.write_text("passed\n", encoding="utf-8")
            evidence_ref = evidence.relative_to(repo).as_posix()
            state = run_state.build_state("run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED")
            state["dispatch"] = {
                "status": "worker_running",
                "current_task_id": "T03",
                "current_agent": "code-developer-order-service",
                "worker_handle": "fresh-worker-T03",
                "worker_session": "fresh-worker-session-T03",
                "spawn_acknowledged_at": "2026-06-03T14:44:24Z",
                "spawn_confirmed_by": "dispatch_ack",
            }
            state["dispatches"] = {"T03": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "tasks": [
                            {
                                "id": "T03",
                                "phase": "implement",
                                "agent": "code-developer-order-service",
                                "service": "services/order-service",
                                "status": "claimed",
                                "owner": "code-developer-order-service",
                                "outputs": [evidence_ref],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            approval.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.recovery-approval.v1",
                        "task_id": "T03",
                        "agent": "code-developer-order-service",
                        "approved": True,
                        "expires_at": "2099-01-01T00:00:00Z",
                        "allowed_evidence": [evidence_ref],
                        "evidence_hashes": {evidence_ref: hashlib.sha256(evidence.read_bytes()).hexdigest()},
                    }
                ),
                encoding="utf-8",
            )

            code, result = e2e_dev_harness.dispatch_complete(
                SimpleNamespace(
                    repo=repo,
                    schedule=schedule_path,
                    state=state_path,
                    task_id="T03",
                    agent="code-developer-order-service",
                    evidence=[evidence_ref],
                    manual_recovery=True,
                    recovery_approval=approval,
                    status_file=None,
                )
            )
            updated_schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
            updated_state = json.loads(state_path.read_text(encoding="utf-8"))
            event = json.loads((state_path.parent / "dispatch-events" / "T03-completed.json").read_text(encoding="utf-8"))

        self.assertEqual(0, code)
        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("completed", updated_schedule["tasks"][0]["status"])
        self.assertEqual("worker_completed", updated_state["dispatches"]["T03"]["status"])
        self.assertTrue(event["manual_recovery"])

    def test_dispatch_complete_manual_recovery_blocks_expired_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            evidence = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service" / "unit-test-evidence.txt"
            approval = repo / "docs" / "agent-runs" / "run" / "recovery-requests" / "T03-expired.json"
            evidence.parent.mkdir(parents=True)
            approval.parent.mkdir(parents=True)
            evidence.write_text("passed\n", encoding="utf-8")
            evidence_ref = evidence.relative_to(repo).as_posix()
            state = run_state.build_state("run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED")
            state["dispatch"] = {
                "status": "worker_running",
                "current_task_id": "T03",
                "current_agent": "code-developer-order-service",
                "worker_handle": "fresh-worker-T03",
                "worker_session": "fresh-worker-session-T03",
                "spawn_acknowledged_at": "2026-06-03T14:44:24Z",
                "spawn_confirmed_by": "dispatch_ack",
            }
            state["dispatches"] = {"T03": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "tasks": [
                            {
                                "id": "T03",
                                "phase": "implement",
                                "agent": "code-developer-order-service",
                                "service": "services/order-service",
                                "status": "claimed",
                                "owner": "code-developer-order-service",
                                "outputs": [evidence_ref],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            approval.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.recovery-approval.v1",
                        "task_id": "T03",
                        "agent": "code-developer-order-service",
                        "approved": True,
                        "expires_at": "2000-01-01T00:00:00Z",
                        "allowed_evidence": [evidence_ref],
                        "evidence_hashes": {evidence_ref: hashlib.sha256(evidence.read_bytes()).hexdigest()},
                    }
                ),
                encoding="utf-8",
            )

            code, result = e2e_dev_harness.dispatch_complete(
                SimpleNamespace(
                    repo=repo,
                    schedule=schedule_path,
                    state=state_path,
                    task_id="T03",
                    agent="code-developer-order-service",
                    evidence=[evidence_ref],
                    manual_recovery=True,
                    recovery_approval=approval,
                    status_file=None,
                )
            )
            updated_schedule = json.loads(schedule_path.read_text(encoding="utf-8"))

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])
        self.assertTrue(any("expired" in reason.lower() for reason in result["blocked_reasons"]))
        self.assertEqual("claimed", updated_schedule["tasks"][0]["status"])

    def test_dispatch_complete_manual_recovery_blocks_approval_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            evidence = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service" / "unit-test-evidence.txt"
            approval = repo / "docs" / "agent-runs" / "run" / "recovery-requests" / "T03-wrong-task.json"
            evidence.parent.mkdir(parents=True)
            approval.parent.mkdir(parents=True)
            evidence.write_text("passed\n", encoding="utf-8")
            evidence_ref = evidence.relative_to(repo).as_posix()
            state = run_state.build_state("run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED")
            state["dispatch"] = {
                "status": "worker_running",
                "current_task_id": "T03",
                "current_agent": "code-developer-order-service",
                "worker_handle": "fresh-worker-T03",
                "worker_session": "fresh-worker-session-T03",
                "spawn_acknowledged_at": "2026-06-03T14:44:24Z",
                "spawn_confirmed_by": "dispatch_ack",
            }
            state["dispatches"] = {"T03": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "tasks": [
                            {
                                "id": "T03",
                                "phase": "implement",
                                "agent": "code-developer-order-service",
                                "service": "services/order-service",
                                "status": "claimed",
                                "owner": "code-developer-order-service",
                                "outputs": [evidence_ref],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            approval.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.recovery-approval.v1",
                        "task_id": "T99",
                        "agent": "other-agent",
                        "approved": True,
                        "expires_at": "2099-01-01T00:00:00Z",
                        "allowed_evidence": [evidence_ref],
                        "evidence_hashes": {evidence_ref: hashlib.sha256(evidence.read_bytes()).hexdigest()},
                    }
                ),
                encoding="utf-8",
            )

            code, result = e2e_dev_harness.dispatch_complete(
                SimpleNamespace(
                    repo=repo,
                    schedule=schedule_path,
                    state=state_path,
                    task_id="T03",
                    agent="code-developer-order-service",
                    evidence=[evidence_ref],
                    manual_recovery=True,
                    recovery_approval=approval,
                    status_file=None,
                )
            )

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])
        joined = "\n".join(result["blocked_reasons"]).lower()
        self.assertIn("task mismatch", joined)
        self.assertIn("agent mismatch", joined)

    def test_dispatch_complete_manual_recovery_blocks_evidence_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            evidence = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service" / "unit-test-evidence.txt"
            approval = repo / "docs" / "agent-runs" / "run" / "recovery-requests" / "T03-hash-mismatch.json"
            evidence.parent.mkdir(parents=True)
            approval.parent.mkdir(parents=True)
            evidence.write_text("passed\n", encoding="utf-8")
            evidence_ref = evidence.relative_to(repo).as_posix()
            state = run_state.build_state("run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED")
            state["dispatch"] = {
                "status": "worker_running",
                "current_task_id": "T03",
                "current_agent": "code-developer-order-service",
                "worker_handle": "fresh-worker-T03",
                "worker_session": "fresh-worker-session-T03",
                "spawn_acknowledged_at": "2026-06-03T14:44:24Z",
                "spawn_confirmed_by": "dispatch_ack",
            }
            state["dispatches"] = {"T03": dict(state["dispatch"])}
            run_state.write_state(repo, state_path, state)
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "tasks": [
                            {
                                "id": "T03",
                                "phase": "implement",
                                "agent": "code-developer-order-service",
                                "service": "services/order-service",
                                "status": "claimed",
                                "owner": "code-developer-order-service",
                                "outputs": [evidence_ref],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            approval.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.recovery-approval.v1",
                        "task_id": "T03",
                        "agent": "code-developer-order-service",
                        "approved": True,
                        "expires_at": "2099-01-01T00:00:00Z",
                        "allowed_evidence": [evidence_ref],
                        "evidence_hashes": {evidence_ref: "0" * 64},
                    }
                ),
                encoding="utf-8",
            )

            code, result = e2e_dev_harness.dispatch_complete(
                SimpleNamespace(
                    repo=repo,
                    schedule=schedule_path,
                    state=state_path,
                    task_id="T03",
                    agent="code-developer-order-service",
                    evidence=[evidence_ref],
                    manual_recovery=True,
                    recovery_approval=approval,
                    status_file=None,
                )
            )

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])
        self.assertTrue(any("hash does not match" in reason.lower() for reason in result["blocked_reasons"]))

    def test_agent_task_claim_allows_service_implementation_plan_input_without_ready_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            service_plan = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service" / "implementation-plan.md"
            service_plan.parent.mkdir(parents=True)
            service_plan.write_text("# Service Implementation Plan\n\n## Scope\n- services/order-service/\n", encoding="utf-8")
            state = run_state.build_state("run", "multi", ["services/order-service"], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED")
            run_state.write_state(repo, state_path, state)
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {"id": "T01", "phase": "tdd-red", "status": "completed"},
                            {"id": "T02", "phase": "r2-review", "status": "completed"},
                            {
                                "id": "T03",
                                "agent": "code-developer-order-service",
                                "phase": "implement",
                                "service": "services/order-service",
                                "status": "planned",
                                "depends_on_phases": ["tdd-red", "r2-review"],
                                "inputs": ["docs/agent-runs/run/service-plans/order-service/implementation-plan.md"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = agent_scheduler.claim(repo, schedule_path, "T03", "code-developer-order-service", state_path)

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_agent_task_claim_blocks_same_agent_across_design_test_code_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule_path.parent.mkdir(parents=True)
            schedule = {
                "schema": "e2e-dev-harness.agent-schedule.v1",
                "tasks": [
                    {
                        "id": "T01",
                        "agent": "use-case-designer",
                        "phase": "design",
                        "role_group": "design",
                        "status": "completed",
                        "owner": "agent-alpha",
                    },
                    {
                        "id": "T02",
                        "agent": "test-case-developer",
                        "phase": "tdd-red",
                        "role_group": "test",
                        "status": "planned",
                    },
                    {
                        "id": "T03",
                        "agent": "code-developer",
                        "phase": "implement",
                        "role_group": "code",
                        "status": "planned",
                    },
                ],
            }
            schedule_path.write_text(json.dumps(schedule), encoding="utf-8")

            blocked = agent_scheduler.claim(repo, schedule_path, "T02", "agent-alpha")
            allowed = agent_scheduler.claim(repo, schedule_path, "T02", "agent-beta")

        self.assertFalse(blocked["ready"])
        self.assertTrue(any("cannot own both test and design" in reason for reason in blocked["blocked_reasons"]))
        self.assertTrue(allowed["ready"], allowed["blocked_reasons"])

    def test_agent_task_claim_requires_ready_input_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            handoff = repo / "docs" / "agent-runs" / "run" / "handoffs" / "01-requirements-clarifier.md"
            handoff.parent.mkdir(parents=True)
            handoff.write_text(e2e_dev_harness.handoff_text("requirements-clarifier"), encoding="utf-8")
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "role_group": "design",
                                "status": "completed",
                            },
                            {
                                "id": "T02",
                                "agent": "use-case-designer",
                                "phase": "design",
                                "role_group": "design",
                                "status": "planned",
                                "depends_on_phases": ["clarify"],
                                "inputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = agent_scheduler.claim(repo, schedule_path, "T02", "agent-designer")

        self.assertFalse(result["ready"])
        self.assertTrue(any("input handoff is not ready" in reason for reason in result["blocked_reasons"]))

    def test_agent_task_claim_requires_existing_role_template_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule_path.parent.mkdir(parents=True)
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "code-developer",
                                "phase": "implement",
                                "role_group": "code",
                                "status": "planned",
                                "role_template": "docs/agent-runs/run/agent-roles/code-developer.md",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            missing = agent_scheduler.claim(repo, schedule_path, "T01", "agent-code")
            template = repo / "docs" / "agent-runs" / "run" / "agent-roles" / "code-developer.md"
            template.parent.mkdir(parents=True)
            template.write_text(e2e_dev_harness.role_template_text("code-developer"), encoding="utf-8")
            ok = agent_scheduler.claim(repo, schedule_path, "T01", "agent-code")

        self.assertFalse(missing["ready"])
        self.assertTrue(any("role_template is missing" in reason for reason in missing["blocked_reasons"]))
        self.assertTrue(ok["ready"], ok["blocked_reasons"])

    def test_create_archive_writes_role_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifacts = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

            created = e2e_dev_harness.create_handoff_files(repo, artifacts)
            template = repo / artifacts["role_templates"]["code-developer"]
            text = template.read_text(encoding="utf-8")

        self.assertTrue(any("agent-roles" in path for path in created))
        self.assertIn("## Role Boundary", text)
        self.assertIn("## Forbidden", text)
        self.assertIn("Do not alter requirements", text)

    def test_agent_task_complete_requires_service_artifacts_and_passed_unit_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            base = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service"
            base.mkdir(parents=True)
            unit = base / "unit-test-evidence.json"
            manifest = base / "implementation-manifest.md"
            coverage = base / "coverage-matrix.md"
            unit.write_text(json.dumps([{"command": "mvn -pl order-service test", "exit_code": 0}]), encoding="utf-8")
            manifest.write_text(
                "| id | module | artifact | artifact_type | source | required | tests | status | evidence |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| IM-1 | order-service | OrderService | service | AC-1 | yes | OrderServiceTest | verified | unit |\n",
                encoding="utf-8",
            )
            coverage.write_text(
                "| id | acceptance | use_case | service | tests | code_refs | business_review | status |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| AC-1 | ok | UC-1 | order-service | OrderServiceTest | OrderService | reviewed | verified |\n",
                encoding="utf-8",
            )
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "phase": "implement",
                                "service": "services/order-service",
                                "status": "claimed",
                                "owner": "agent-order",
                                "outputs": [
                                    "docs/agent-runs/run/service-plans/order-service/unit-test-evidence.json",
                                    "docs/agent-runs/run/service-plans/order-service/implementation-manifest.md",
                                    "docs/agent-runs/run/service-plans/order-service/coverage-matrix.md",
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = agent_scheduler.complete(
                repo,
                schedule_path,
                "T01",
                "agent-order",
                evidence=[
                    "docs/agent-runs/run/service-plans/order-service/unit-test-evidence.json",
                    "docs/agent-runs/run/service-plans/order-service/implementation-manifest.md",
                    "docs/agent-runs/run/service-plans/order-service/coverage-matrix.md",
                ],
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_agent_task_complete_blocks_template_manifest_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            base = repo / "docs" / "agent-runs" / "run" / "service-plans" / "order-service"
            base.mkdir(parents=True)
            manifest = base / "implementation-manifest.md"
            manifest.write_text("TODO template\n", encoding="utf-8")
            schedule_path = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            schedule_path.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "phase": "implement",
                                "service": "services/order-service",
                                "status": "claimed",
                                "owner": "agent-order",
                                "outputs": ["docs/agent-runs/run/service-plans/order-service/implementation-manifest.md"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = agent_scheduler.complete(
                repo,
                schedule_path,
                "T01",
                "agent-order",
                evidence=["docs/agent-runs/run/service-plans/order-service/implementation-manifest.md"],
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("placeholder/template" in reason for reason in result["blocked_reasons"]))

    def test_clarify_auto_transitions_run_state_when_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Restated Intent
                    - The user wants a quote returned.
                    - User confirmation: confirmed-by: user @2026-06-02

                    ## Goal
                    - Return a quote.

                    ## Scope
                    - services/sample-service

                    ## Use Cases
                    - Create quote.

                    ## Acceptance Criteria
                    - AC-1 Quote is returned.

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None. confirmed-by: user @2026-06-02
                    """
                ).strip(),
                encoding="utf-8",
            )
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            schedule = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            write_role_template(repo, role_template)
            write_ready_handoff(repo, evidence, agent_id="requirements-clarifier")
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "worker-1",
                "worker_session": "worker-session-1",
            }
            state["dispatches"] = {"T01": state["dispatch"]}
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "role_group": "design",
                                "inputs": [],
                                "outputs": [evidence.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            complete = dispatcher.dispatch_complete(repo, schedule, state_path, "T01", "requirements-clarifier", [evidence.as_posix()])
            args = SimpleNamespace(
                repo=repo,
                design_doc=Path("docs/design/feature.md"),
                run_state=state_path,
                status_file=None,
            )

            code, result = e2e_dev_harness.clarify(args)
            updated = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(complete["ready"], complete["blocked_reasons"])
        self.assertEqual(0, code, result)
        self.assertEqual("CLARIFIED", updated["lifecycle"])
        self.assertEqual("passed", updated["gates"]["clarification"])
        self.assertTrue(result["run_state_transition"]["ready"])
        self.assertTrue(result["blocked_next_without_plan"])
        self.assertFalse(result["next_required"]["code_writes_allowed"])

    def test_clarify_auto_completes_single_requirements_worker_when_handoff_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Restated Intent
                    - The user wants a quote returned.
                    - User confirmation: confirmed-by: user @2026-06-02

                    ## Goal
                    - Return a quote.

                    ## Scope
                    - services/sample-service

                    ## Use Cases
                    - Create quote.

                    ## Acceptance Criteria
                    - AC-1 Quote is returned.

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None. confirmed-by: user @2026-06-02
                    """
                ).strip(),
                encoding="utf-8",
            )
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            evidence = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            schedule = repo / "docs" / "agent-runs" / "run" / "agent-schedule.json"
            write_role_template(repo, role_template)
            write_ready_handoff(repo, evidence, agent_id="requirements-clarifier")
            state["dispatch"] = {
                "status": "worker_running",
                "runtime": "codex",
                "current_task_id": "T01",
                "current_agent": "requirements-clarifier",
                "worker_handle": "worker-1",
                "worker_session": "worker-session-1",
            }
            state["dispatches"] = {"T01": state["dispatch"]}
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "role_group": "design",
                                "inputs": [],
                                "outputs": [evidence.as_posix()],
                                "role_template": role_template.as_posix(),
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                repo=repo,
                design_doc=Path("docs/design/feature.md"),
                run_state=state_path,
                status_file=None,
            )

            code, result = e2e_dev_harness.clarify(args)
            updated = json.loads(state_path.read_text(encoding="utf-8"))
            event = json.loads((state_path.parent / "dispatch-events" / "T01-completed.json").read_text(encoding="utf-8"))

        self.assertEqual(0, code, result)
        self.assertEqual("CLARIFIED", updated["lifecycle"])
        self.assertEqual("worker_completed", updated["dispatches"]["T01"]["status"])
        self.assertEqual("worker_completed", event["event"])
        self.assertTrue(result["clarification_dispatch_auto_complete"]["ready"])

    def test_clarify_blocks_created_run_state_without_requirements_worker_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Restated Intent
                    - The user wants a quote returned.
                    - User confirmation: confirmed-by: user @2026-06-02

                    ## Goal
                    - Return a quote.

                    ## Scope
                    - services/sample-service

                    ## Use Cases
                    - Create quote.

                    ## Acceptance Criteria
                    - AC-1 Quote is returned.

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None. confirmed-by: user @2026-06-02
                    """
                ).strip(),
                encoding="utf-8",
            )
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)
            args = SimpleNamespace(
                repo=repo,
                design_doc=Path("docs/design/feature.md"),
                run_state=state_path,
                status_file=None,
            )

            code, result = e2e_dev_harness.clarify(args)
            updated = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(2, code)
        self.assertFalse(result["ready_for_implementation"])
        self.assertTrue(any("requirements-clarifier" in reason for reason in result["blocked_reasons"]))
        self.assertEqual("CREATED", updated["lifecycle"])
        self.assertEqual("planned", updated["gates"]["clarification"])

    def test_gate_auto_transitions_implementation_phase_when_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red-test.txt"
            red.parent.mkdir(parents=True)
            red.write_text("expected failure\n", encoding="utf-8")
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)
            args = SimpleNamespace(
                repo=repo,
                design_doc=None,
                kg_status_file=None,
                phase="implementation",
                red_test_evidence=red,
                coverage_matrix=None,
                unit_test_evidence=None,
                business_review=None,
                memory_updates=None,
                skip_spring_static_check=False,
                rework_dir=None,
                dependency_report=None,
                implementation_manifest=None,
                review_dir=None,
                review_profile=None,
                handoff_dir=None,
                contract_dir=None,
                require_contracts=False,
                require_handoffs=False,
                require_semantic_reviews=False,
                requirements_archive=None,
                require_requirements_archive=False,
                strict_workflow=False,
                run_state=state_path,
                status_file=None,
            )

            with patch.object(
                e2e_dev_harness.implementation_gate,
                "validate_gate_request",
                return_value={
                    "ready": True,
                    "blocked_reasons": [],
                    "warnings": [],
                    **implementation_gate_payload(red),
                },
            ):
                code, result = e2e_dev_harness.gate(args)
            updated = json.loads(state_path.read_text(encoding="utf-8"))
            lock = json.loads((state_path.parent / ".phase-lock").read_text(encoding="utf-8"))

        self.assertEqual(0, code, result)
        self.assertEqual("IMPLEMENTED", updated["lifecycle"])
        self.assertEqual("passed", updated["gates"]["implementation"])
        self.assertEqual("code-write-open", lock["state"])
        self.assertTrue(result["run_state_transition"]["ready"])

    def test_phase_guard_blocks_code_write_before_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/main/java/PaymentService.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Code write blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_blocks_claude_update_tool_before_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Update",
                [Path("jeepay-payment/src/main/java/com/jeequan/jeepay/pay/service/RiskControlService.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Code write blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_fails_closed_for_unknown_code_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            result = phase_guard.validate_action(
                repo,
                "PatchFile",
                [Path("jeepay-core/src/main/java/com/jeequan/jeepay/core/entity/PayOrder.java")],
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("unrecognized tool" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_blocks_stale_phase_lock_when_run_state_is_not_implemented(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            run_state.write_state(repo, state_path, state)
            lock_path = state_path.parent / ".phase-lock"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["lifecycle"] = "IMPLEMENTED"
            lock["state"] = "code-write-open"
            lock_path.write_text(json.dumps(lock, indent=2), encoding="utf-8")

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/main/java/PaymentService.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("does not match run-state lifecycle" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_blocks_direct_harness_control_file_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("docs/agent-runs/run/.phase-lock")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Harness control file write blocked" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(result["not_deadlock"])
        self.assertIn("next_valid_command", result)
        self.assertTrue(any("disable or edit harness hooks" in action for action in result["forbidden_actions"]))

    def test_phase_guard_blocks_direct_hook_config_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Write",
                [Path(".claude/settings.json")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("hook config edit blocked" in reason.lower() for reason in result["blocked_reasons"]))
        self.assertEqual("CREATED", result["lifecycle"])
        self.assertTrue(result["not_deadlock"])
        self.assertIn("requirements-clarifier", " ".join(result["allowed_actions"]).lower())

    def test_phase_guard_blocks_apply_patch_delete_of_harness_control_file(self) -> None:
        patch_text = "*** Begin Patch\n*** Delete File: docs/agent-runs/run/run-state.json\n*** End Patch\n"
        hook_text = json.dumps({"tool_name": "ApplyPatch", "tool_input": {"patch": patch_text}})
        tool, paths = phase_guard.parse_hook_input(hook_text)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths])

        self.assertEqual("ApplyPatch", tool)
        self.assertEqual(["docs/agent-runs/run/run-state.json"], paths)
        self.assertFalse(result["ready"])
        self.assertTrue(any("Harness control file write blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_blocks_forged_implemented_state_and_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            run_state.write_state(repo, state_path, state)
            state["lifecycle"] = "IMPLEMENTED"
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
            lock_path = state_path.parent / ".phase-lock"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["lifecycle"] = "IMPLEMENTED"
            lock["state"] = "code-write-open"
            lock_path.write_text(json.dumps(lock, indent=2), encoding="utf-8")

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/main/java/PaymentService.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("transition history" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_blocks_inline_python_control_file_mutation(self) -> None:
        hook_text = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "python -c \"from pathlib import Path; "
                        "p=Path('docs/agent-runs/run/.phase-lock'); "
                        "p.write_text('{\\\"lifecycle\\\":\\\"IMPLEMENTED\\\"}')\""
                    )
                },
            }
        )
        tool, paths = phase_guard.parse_hook_input(hook_text)
        command_text = phase_guard.extract_hook_command_text(hook_text)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths], command_text=command_text)

        self.assertFalse(result["ready"])
        self.assertTrue(any("Harness control file write blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_blocks_large_inline_coordinator_write_payload(self) -> None:
        hook_text = json.dumps(
            {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "docs/agent-runs/run/handoffs/worker-handoff.md",
                    "content": "x" * 25000,
                },
            }
        )
        tool, paths = phase_guard.parse_hook_input(hook_text)
        payload_text = phase_guard.extract_hook_write_payload_text(hook_text)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            result = phase_guard.validate_action(
                repo,
                tool,
                [Path(path) for path in paths],
                write_payload_text=payload_text,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Coordinator write budget blocked" in reason for reason in result["blocked_reasons"]))
        self.assertIn("coordinator_write_budget", result)
        self.assertEqual(25000, result["coordinator_write_budget"]["inline_payload_chars"])

    def test_phase_guard_warns_on_medium_inline_coordinator_write_payload(self) -> None:
        hook_text = json.dumps(
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": "docs/agent-runs/run/handoffs/worker-handoff.md",
                    "old_string": "before",
                    "new_string": "x" * 9000,
                },
            }
        )
        tool, paths = phase_guard.parse_hook_input(hook_text)
        payload_text = phase_guard.extract_hook_write_payload_text(hook_text)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            result = phase_guard.validate_action(
                repo,
                tool,
                [Path(path) for path in paths],
                write_payload_text=payload_text,
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(any("Coordinator write budget warning" in warning for warning in result["warnings"]))
        self.assertIn("coordinator_write_budget", result)

    def test_phase_guard_allows_harness_cli_referencing_run_state(self) -> None:
        hook_text = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "python skills/e2e-dev-harness/scripts/e2e_dev_harness.py clarify "
                        "--design-doc docs/design/URCS.md "
                        "--run-state docs/agent-runs/run/run-state.json 2>&1"
                    )
                },
            }
        )
        tool, paths = phase_guard.parse_hook_input(hook_text)
        command_text = phase_guard.extract_hook_command_text(hook_text)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)
            result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths], command_text=command_text)

        self.assertIn("docs/agent-runs/run/run-state.json", paths)
        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_phase_guard_blocks_unscoped_inline_shell_mutation(self) -> None:
        hook_text = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "python -c \"target='services/' + 'payment/src/main/java/Pay.java'; open(target, 'w').write('x')\""
                },
            }
        )
        tool, paths = phase_guard.parse_hook_input(hook_text)
        command_text = phase_guard.extract_hook_command_text(hook_text)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths], command_text=command_text)

        self.assertFalse(result["ready"])
        self.assertTrue(any("Shell write blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_blocks_tee_code_write_before_phase_lock(self) -> None:
        hook_text = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "printf 'class Pay {}' | tee services/payment/src/main/java/Pay.java"
                },
            }
        )
        tool, paths = phase_guard.parse_hook_input(hook_text)
        command_text = phase_guard.extract_hook_command_text(hook_text)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths], command_text=command_text)

        self.assertIn("services/payment/src/main/java/Pay.java", paths)
        self.assertFalse(result["ready"])
        self.assertTrue(any("Code write blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_blocks_heredoc_code_write_before_phase_lock(self) -> None:
        hook_text = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "cat <<'EOF' > services/payment/src/main/java/Pay.java\nclass Pay {}\nEOF"
                },
            }
        )
        tool, paths = phase_guard.parse_hook_input(hook_text)
        command_text = phase_guard.extract_hook_command_text(hook_text)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths], command_text=command_text)

        self.assertIn("services/payment/src/main/java/Pay.java", paths)
        self.assertFalse(result["ready"])
        self.assertTrue(any("Code write blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_allows_readonly_bash_without_active_run(self) -> None:
        hook_text = json.dumps({"tool_name": "Bash", "tool_input": {"command": "python --version"}})
        tool, paths = phase_guard.parse_hook_input(hook_text)
        command_text = phase_guard.extract_hook_command_text(hook_text)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths], command_text=command_text)

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_phase_guard_blocks_code_read_before_start_when_entry_guard_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            result = phase_guard.validate_action(
                repo,
                "Read",
                [Path("services/payment/src/main/java/PayOrder.java")],
                require_active_run_for_read=True,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Code exploration blocked" in reason for reason in result["blocked_reasons"]))
        self.assertIn("Read", result["allowed_direct_exploration_tools"])
        self.assertIn("Grep", result["allowed_direct_exploration_tools"])
        self.assertIn("start", result["direct_exploration_guidance"].lower())

    def test_phase_guard_blocks_code_read_in_created_before_clarifier_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Read",
                [Path("services/payment/src/main/java/PayOrder.java")],
                run_dir=Path("docs/agent-runs/run"),
                require_active_run_for_read=True,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("requirements-clarifier" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("design-doc analysis may continue" in reason for reason in result["blocked_reasons"]))
        self.assertIn("required_todo_list", result)
        self.assertEqual(
            ["design-doc requirements analysis", "Restated Intent", "Open Questions"],
            result["exploration_policy"]["direct_tools_allowed_for"],
        )
        self.assertEqual(
            ["code Read/Grep/Glob", "GitNexus impact evidence", "implementation planning"],
            result["exploration_policy"]["direct_tools_blocked_for"],
        )

    def test_phase_guard_blocks_code_read_in_dispatch_lifecycle_without_active_worker(self) -> None:
        for lifecycle in ("CLARIFIED", "SERVICE_DESIGN_REQUIRED", "PLANNED", "IMPLEMENTED"):
            with self.subTest(lifecycle=lifecycle):
                with tempfile.TemporaryDirectory() as tmp:
                    repo = Path(tmp)
                    state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
                    state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", lifecycle)
                    if lifecycle == "IMPLEMENTED":
                        write_implemented_state(repo, state_path, state)
                    else:
                        run_state.write_state(repo, state_path, state)

                    result = phase_guard.validate_action(
                        repo,
                        "Read",
                        [Path("services/payment/src/main/java/PayOrder.java")],
                        run_dir=Path("docs/agent-runs/run"),
                        require_active_run_for_read=True,
                    )

                self.assertFalse(result["ready"])
                self.assertTrue(any("active dispatched worker" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_parses_common_read_path_fields(self) -> None:
        hook_text = json.dumps(
            {
                "tool_name": "Read",
                "tool_input": {
                    "filePath": "services/payment/src/main/java/PayOrder.java",
                    "absolutePath": "C:/repo/services/payment/src/main/java/PayOrder.java",
                },
            }
        )

        tool, paths = phase_guard.parse_hook_input(hook_text)

        self.assertEqual("Read", tool)
        self.assertIn("services/payment/src/main/java/PayOrder.java", paths)
        self.assertIn("C:/repo/services/payment/src/main/java/PayOrder.java", paths)

    def test_phase_guard_allows_read_outside_target_repo_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            outside = Path(tmp) / "other" / "PayOrder.java"
            outside.parent.mkdir()
            outside.write_text("class PayOrder {}", encoding="utf-8")

            result = phase_guard.validate_action(
                repo,
                "Read",
                [outside],
                require_active_run_for_read=True,
                require_session_checkpoint=True,
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(any("outside the configured harness repository" in warning for warning in result["warnings"]))

    def test_phase_guard_blocks_code_agent_dispatch_before_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Task",
                [],
                run_dir=Path("docs/agent-runs/run"),
                task_text="Implement the payment service and write production code.",
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Code-agent dispatch blocked" in reason for reason in result["blocked_reasons"]))
        self.assertIn("Read", result["allowed_direct_exploration_tools"])
        self.assertIn("Grep", result["allowed_direct_exploration_tools"])
        self.assertIn("direct", result["direct_exploration_guidance"].lower())
        self.assertIn("dispatcher-generated", result["agent_dispatch_guidance"].lower())

    def test_phase_guard_blocks_free_form_phase_task_without_dispatch_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "bootstrap", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Task",
                [],
                run_dir=Path("docs/agent-runs/run"),
                task_text="Clarify requirements, update open questions, and write the requirements handoff.",
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("dispatcher-generated" in reason.lower() for reason in result["blocked_reasons"]))

    def test_phase_guard_allows_read_only_exploration_task_with_phase_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "bootstrap", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Task",
                [],
                run_dir=Path("docs/agent-runs/run"),
                task_text="Read-only exploration: review the repo layout and summarize where tests live. Do not edit files.",
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_phase_guard_allows_dispatcher_generated_clarification_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            schedule = run_dir / "agent-schedule.json"
            role_template = Path("docs/agent-runs/run/agent-roles/requirements-clarifier.md")
            design = Path("docs/design/refund.md")
            write_role_template(repo, role_template)
            (repo / design).parent.mkdir(parents=True, exist_ok=True)
            (repo / design).write_text("# Refund\n", encoding="utf-8")
            state = run_state.build_state("docs/agent-runs/run", "bootstrap", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            run_state.write_state(repo, state_path, state)
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "completion_mode": "dispatcher-confirmed",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "role_group": "design",
                                "dispatch_contract": "fresh-subagent",
                                "runtime_subagent_type": "requirements-clarifier",
                                "inputs": ["user request", design.as_posix()],
                                "outputs": ["docs/agent-runs/run/handoffs/01-requirements-clarifier.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            dispatch_result = dispatcher.dispatch_next(repo, schedule, state_path, runtime="codex")

            result = phase_guard.validate_action(
                repo,
                "Task",
                [],
                run_dir=Path("docs/agent-runs/run"),
                task_text=dispatch_result["task_prompt"],
            )

        self.assertTrue(dispatch_result["ready"], dispatch_result["blocked_reasons"])
        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_phase_guard_blocks_code_agent_dispatch_without_dispatch_packet_after_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "multi", ["services/payment"], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            write_implemented_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Task",
                [],
                run_dir=Path("docs/agent-runs/run"),
                task_text="Implement the payment service and write production code.",
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("dispatcher context pack" in reason.lower() for reason in result["blocked_reasons"]))

    def test_phase_guard_allows_dispatcher_generated_code_agent_task_after_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            schedule = run_dir / "agent-schedule.json"
            role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            write_role_template(repo, role_template)
            write_ready_handoff(repo, handoff)
            state = run_state.build_state("run", "multi", ["services/payment"], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            write_implemented_state(repo, state_path, state)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T10",
                                "agent": "code-developer-payment",
                                "phase": "implement",
                                "role_group": "code",
                                "dispatch_contract": "fresh-subagent",
                                "runtime_subagent_type": "code-developer",
                                "service": "services/payment",
                                "inputs": [handoff.as_posix()],
                                "outputs": ["docs/agent-runs/run/service-plans/payment/code-agent.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            dispatch_result = dispatcher.dispatch_next(repo, schedule, state_path, runtime="claude-code")

            result = phase_guard.validate_action(
                repo,
                "Task",
                [],
                run_dir=Path("docs/agent-runs/run"),
                task_text=dispatch_result["task_prompt"],
            )

        self.assertTrue(dispatch_result["ready"], dispatch_result["blocked_reasons"])
        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_phase_guard_does_not_auto_confirm_dispatcher_generated_review_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            schedule = run_dir / "agent-schedule.json"
            role_template = Path("docs/agent-runs/run/agent-roles/semantic-reviewer.md")
            review_request = Path("docs/agent-runs/run/review-requests/R1-design-review-request.md")
            write_role_template(repo, role_template)
            (repo / review_request).parent.mkdir(parents=True, exist_ok=True)
            (repo / review_request).write_text(
                textwrap.dedent(
                    """
                    # R1 Review Request

                    - Phase: design
                    - Reviewer Role: independent semantic reviewer
                    - Context Package: request-scoped; no inherited developer chat context
                    - Forbidden: inherited developer chat context; production-code edits; self-review
                    - Output: docs/agent-runs/run/reviews/R1-design-review.md
                    - Developer Agent: coordinator-agent
                    - Reviewer Agent: design-reviewer
                    - Reviewer Invocation: docs/agent-runs/run/review-invocations/R1-design-review-invocation.json
                    """
                ).strip(),
                encoding="utf-8",
            )
            state = run_state.build_state("run", "single-review", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "require_role_templates": True,
                        "tasks": [
                            {
                                "id": "T04",
                                "agent": "design-reviewer",
                                "phase": "r1-review",
                                "role_group": "review",
                                "dispatch_contract": "fresh-subagent",
                                "runtime_subagent_type": "semantic-reviewer",
                                "inputs": [review_request.as_posix()],
                                "outputs": ["docs/agent-runs/run/reviews/R1-design-review.md"],
                                "role_template": role_template.as_posix(),
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            dispatch_result = dispatcher.dispatch_next(repo, schedule, state_path, runtime="codex")
            before_hook = json.loads(state_path.read_text(encoding="utf-8"))

            result = phase_guard.validate_action(
                repo,
                "Task",
                [],
                run_dir=Path("docs/agent-runs/run"),
                task_text=dispatch_result["task_prompt"],
            )
            after_hook = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(dispatch_result["ready"], dispatch_result["blocked_reasons"])
        self.assertEqual("awaiting_runtime_spawn", before_hook["dispatch"]["status"])
        self.assertTrue(result["ready"], result["blocked_reasons"])
        # Option A: phase_guard must not fabricate a confirmed spawn state.
        self.assertEqual("awaiting_runtime_spawn", after_hook["dispatch"]["status"])
        self.assertNotEqual("phase_guard", after_hook["dispatch"].get("spawn_confirmed_by"))
        self.assertTrue(
            any("dispatch-ack" in str(w) for w in result.get("warnings", [])),
            result.get("warnings"),
        )

    def test_phase_guard_blocks_direct_reviewer_report_write_without_active_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            schedule = run_dir / "agent-schedule.json"
            review = Path("docs/agent-runs/run/reviews/R1-design-review.md")
            state = run_state.build_state("run", "single-review", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            run_state.write_state(repo, state_path, state)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T04",
                                "agent": "design-reviewer",
                                "phase": "r1-review",
                                "role_group": "review",
                                "outputs": [review.as_posix()],
                                "status": "claimed",
                                "owner": "design-reviewer",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = phase_guard.validate_action(
                repo,
                "Write",
                [review],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("Review report write blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_blocks_coordinator_write_to_active_worker_output_without_task_hook_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            schedule = run_dir / "agent-schedule.json"
            output = Path("docs/agent-runs/run/evidence/impact-summary.md")
            state = run_state.build_state("run", "bootstrap", [], "docs/agent-runs/run/artifact-registry.json", "CREATED")
            state["dispatches"] = {
                "T01": {
                    "status": "worker_running",
                    "current_task_id": "T01",
                    "current_agent": "requirements-clarifier",
                    "worker_handle": "manual-worker-T01",
                    "worker_session": "manual-worker-session-T01",
                    "spawn_acknowledged_at": "2026-06-03T14:44:24Z",
                    "spawn_confirmed_by": "dispatch_ack",
                }
            }
            state["dispatch"] = state["dispatches"]["T01"]
            run_state.write_state(repo, state_path, state)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "requirements-clarifier",
                                "phase": "clarify",
                                "role_group": "design",
                                "outputs": [output.as_posix()],
                                "status": "claimed",
                                "owner": "requirements-clarifier",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = phase_guard.validate_action(
                repo,
                "Write",
                [output],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("worker output write blocked" in reason.lower() for reason in result["blocked_reasons"]))

    def test_phase_guard_allows_reviewer_report_write_from_active_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            schedule = run_dir / "agent-schedule.json"
            review = Path("docs/agent-runs/run/reviews/R1-design-review.md")
            state = run_state.build_state("run", "single-review", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            state["dispatches"] = {
                "T04": {
                    "status": "worker_running",
                    "current_task_id": "T04",
                    "current_agent": "design-reviewer",
                    "parallel_group": "r1-review",
                    "context_pack": "docs/agent-runs/run/context-packs/T04.json",
                    "invocation_path": "docs/agent-runs/run/review-invocations/R1-design-review-invocation.json",
                    "worker_handle": "review-worker-1",
                    "spawn_acknowledged_at": "2026-05-31T00:00:00Z",
                }
            }
            state["dispatch"] = state["dispatches"]["T04"]
            run_state.write_state(repo, state_path, state)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T04",
                                "agent": "design-reviewer",
                                "phase": "r1-review",
                                "role_group": "review",
                                "outputs": [review.as_posix()],
                                "status": "claimed",
                                "owner": "design-reviewer",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = phase_guard.validate_action(
                repo,
                "Write",
                [review],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_phase_guard_blocks_free_form_reviewer_task_before_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Task",
                [],
                run_dir=Path("docs/agent-runs/run"),
                task_text="Run R1 design review and check requirements coverage.",
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("dispatcher-generated" in reason.lower() for reason in result["blocked_reasons"]))

    def test_run_state_validation_blocks_forged_implemented_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            registry = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            registry.parent.mkdir(parents=True)
            registry.write_text('{"schema":"e2e-dev-harness.artifact-registry.v1","artifacts":[]}\n', encoding="utf-8")
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            run_state.write_state(repo, state_path, state)

            result = run_state.validate_state(repo, state_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("transition history" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_blocks_red_test_write_in_planned_without_active_test_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)
            lock = json.loads((state_path.parent / ".phase-lock").read_text(encoding="utf-8"))

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/test/java/PaymentServiceTest.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertEqual("test-write-open", lock["state"])
        self.assertIn("PLANNED", lock["allowed_test_write_lifecycles"])
        self.assertFalse(result["ready"])
        self.assertTrue(any("test-case-developer" in reason for reason in result["blocked_reasons"]))
        self.assertEqual(["services/payment-service/src/test/java/PaymentServiceTest.java"], result["test_code_paths"])

    def test_phase_guard_allows_red_test_write_from_active_test_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            state["dispatches"] = {
                "T05": {
                    "status": "worker_running",
                    "current_task_id": "T05",
                    "current_agent": "test-case-developer",
                    "worker_handle": "test-worker-1",
                }
            }
            state["dispatch"] = state["dispatches"]["T05"]
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/test/java/PaymentServiceTest.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_phase_guard_blocks_mixed_test_and_runtime_write_in_planned_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "MultiEdit",
                [
                    Path("services/payment-service/src/test/java/PaymentServiceTest.java"),
                    Path("services/payment-service/src/main/java/PaymentService.java"),
                ],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertEqual(["services/payment-service/src/main/java/PaymentService.java"], result["runtime_code_paths"])
        self.assertTrue(any("Code write blocked" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_parses_apply_patch_hook_paths(self) -> None:
        hook_text = json.dumps(
            {
                "tool_name": "apply_patch",
                "tool_input": {
                    "patch": textwrap.dedent(
                        """
                        *** Begin Patch
                        *** Update File: services/payment-service/src/main/java/PaymentService.java
                        @@
                        +changed
                        *** End Patch
                        """
                    )
                },
            }
        )

        tool, paths = phase_guard.parse_hook_input(hook_text)

        self.assertEqual("apply_patch", tool)
        self.assertEqual(["services/payment-service/src/main/java/PaymentService.java"], paths)

    def test_phase_guard_blocks_bash_write_before_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            run_state.write_state(repo, state_path, state)
            hook_text = json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "cat <<'EOF' > services/payment-service/src/main/java/PaymentService.java\nclass X {}\nEOF"
                    },
                }
            )
            tool, paths = phase_guard.parse_hook_input(hook_text)

            result = phase_guard.validate_action(repo, tool, [Path(path) for path in paths], run_dir=Path("docs/agent-runs/run"))

        self.assertEqual(["services/payment-service/src/main/java/PaymentService.java"], paths)
        self.assertFalse(result["ready"])
        self.assertTrue(any("Code write blocked" in reason for reason in result["blocked_reasons"]))

    def test_pre_code_blocks_code_write_before_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            run_state.write_state(repo, state_path, state)

            code, result = e2e_dev_harness.pre_code(
                SimpleNamespace(
                    repo=repo,
                    tool="Edit",
                    path=[Path("services/payment-service/src/main/java/PaymentService.java")],
                    patch=None,
                    command_text="",
                    lock=None,
                    run_dir=Path("docs/agent-runs/run"),
                    status_file=None,
                )
            )

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])

    def test_phase_guard_blocks_code_write_in_implementation_without_active_code_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED")
            write_implemented_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/main/java/PaymentService.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("code-developer" in reason for reason in result["blocked_reasons"]))

    def test_phase_guard_allows_code_write_from_active_code_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED")
            state["dispatches"] = {
                "T07": {
                    "status": "worker_running",
                    "current_task_id": "T07",
                    "current_agent": "code-developer",
                    "worker_handle": "code-worker-1",
                }
            }
            state["dispatch"] = state["dispatches"]["T07"]
            write_implemented_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Edit",
                [Path("services/payment-service/src/main/java/PaymentService.java")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_phase_guard_allows_run_artifact_writes_before_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = phase_guard.validate_action(
                repo,
                "Write",
                [Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")],
                run_dir=Path("docs/agent-runs/run"),
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_stop_guard_blocks_implemented_run_before_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            write_implemented_state(repo, state_path, state)

            result = harness_stop_guard.evaluate(repo, run_state_path=state_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("IMPLEMENTED" in reason for reason in result["blocked_reasons"]))
        self.assertIn("R3 review", result["next_action"])

    def test_stop_guard_allows_verified_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            write_implemented_state(repo, state_path, state)
            completion = state_path.parent / "evidence" / "completion-gate.json"
            completion.write_text(json.dumps({"phase": "completion", "ready": True}), encoding="utf-8")
            transition = run_state.transition_state(
                repo,
                state_path,
                "VERIFIED",
                gate="completion",
                gate_status="passed",
                evidence=completion,
            )
            self.assertTrue(transition["ready"], transition["blocked_reasons"])

            result = harness_stop_guard.evaluate(repo, run_state_path=state_path)

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_stop_guard_strict_blocks_clarified_run_before_planning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "CLARIFIED")
            run_state.write_state(repo, state_path, state)

            result = harness_stop_guard.evaluate(repo, run_state_path=state_path, strict=True)

        self.assertFalse(result["ready"])
        self.assertTrue(any("not terminal" in reason for reason in result["blocked_reasons"]))
        self.assertIn("R1 design review", result["guidance"]["remaining_phases"])
        self.assertIn("Do not ask the user to choose", result["guidance"]["agent_instruction"])

    def test_stop_guard_allows_waiting_dispatch_without_marking_completion_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "multi",
                ["services/order-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            state["dispatch"] = {
                "status": "waiting_dispatch",
                "runtime": "manual",
                "current_task_id": "T10",
                "current_agent": "code-developer-order-service",
            }
            run_state.write_state(repo, state_path, state)

            result = harness_stop_guard.evaluate(repo, run_state_path=state_path, strict=True)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("IMPLEMENTED", result["lifecycle"])
        self.assertTrue(result["dispatch_waiting"])
        self.assertFalse(result["completion_ready"])
        self.assertIn("independent subagent", result["warnings"][0])

    def test_stop_guard_treats_runtime_spawn_statuses_as_dispatch_waiting(self) -> None:
        for status in ("awaiting_runtime_spawn", "worker_running"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
                state = run_state.build_state(
                    "docs/agent-runs/run",
                    "multi",
                    ["services/order-service"],
                    "docs/agent-runs/run/artifact-registry.json",
                    "IMPLEMENTED",
                )
                state["dispatch"] = {
                    "status": status,
                    "runtime": "claude-code",
                    "current_task_id": "T10",
                    "current_agent": "code-developer-order-service",
                }
                run_state.write_state(repo, state_path, state)

                result = harness_stop_guard.evaluate(repo, run_state_path=state_path, strict=True)

            self.assertTrue(result["ready"], result["blocked_reasons"])
            self.assertTrue(result["dispatch_waiting"])
            self.assertFalse(result["completion_ready"])

    def test_stop_guard_treats_multi_dispatch_running_as_dispatch_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state(
                "docs/agent-runs/run",
                "multi",
                ["services/order-service", "services/payment-service"],
                "docs/agent-runs/run/artifact-registry.json",
                "IMPLEMENTED",
            )
            state["dispatches"] = {
                "T10": {"status": "worker_running", "current_task_id": "T10", "current_agent": "agent-a"},
                "T11": {"status": "awaiting_runtime_spawn", "current_task_id": "T11", "current_agent": "agent-b"},
            }
            run_state.write_state(repo, state_path, state)

            result = harness_stop_guard.evaluate(repo, run_state_path=state_path, strict=True)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(result["dispatch_waiting"])
        self.assertEqual(2, len(result["dispatches"]))

    def test_stop_guard_json_hook_writes_blocking_guidance_to_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("docs/agent-runs/run", "single", [], "docs/agent-runs/run/artifact-registry.json", "RED_READY")
            run_state.write_state(repo, state_path, state)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "harness_stop_guard.py"),
                    str(repo),
                    "--run-state",
                    str(state_path),
                    "--strict",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(2, completed.returncode)
        self.assertIn('"ready": false', completed.stdout)
        self.assertIn("HARNESS STOP BLOCKED", completed.stderr)
        self.assertIn("R2 test review", completed.stderr)
        self.assertIn("Do not ask the user to choose", completed.stderr)

    def test_stop_guard_allows_no_active_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = harness_stop_guard.evaluate(Path(tmp))

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_stop_guard_ignores_empty_stale_run_scaffold_without_run_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "2026-06-02-URCS"
            for name in ("agent-roles", "confirmations", "coordinator-results", "evidence"):
                (run_dir / name).mkdir(parents=True)

            result = harness_stop_guard.evaluate(repo)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(any("empty harness run directories" in warning for warning in result["warnings"]))

    def test_stop_guard_blocks_run_directory_without_run_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            (run_dir / "evidence").mkdir(parents=True)
            (run_dir / "evidence" / "partial.txt").write_text("partial\n", encoding="utf-8")

            result = harness_stop_guard.evaluate(repo)

        self.assertFalse(result["ready"])
        self.assertTrue(any("run-state" in reason for reason in result["blocked_reasons"]))

    def test_hook_examples_call_phase_guard(self) -> None:
        hook_dir = ROOT / "skills" / "e2e-dev-harness" / "hooks"

        for name in (
            "claude-code-settings.example.json",
            "codex-pre-action.example.json",
            "gemini-pre-action.example.json",
            "opencode-plugin.example.js",
        ):
            with self.subTest(name=name):
                text = (hook_dir / name).read_text(encoding="utf-8")
                self.assertIn("phase_guard.py", text)
                self.assertNotIn("python skills/e2e-dev-harness/scripts/phase_guard.py .", text)
                self.assertIn("--require-active-run-for-read", text)
                if name == "opencode-plugin.example.js":
                    self.assertIn("tool.execute.before", text)
                    self.assertIn("throw new Error", text)
                if name == "claude-code-settings.example.json":
                    self.assertIn("--require-session-checkpoint", text)
                if name != "opencode-plugin.example.js":
                    self.assertIn("blocking", text.lower() if "claude" not in name else "blocking")
                if name == "claude-code-settings.example.json":
                    self.assertIn("harness_stop_guard.py", text)
                    self.assertIn("--strict", text)
                    self.assertIn("Bash", text)
                    self.assertIn("Update", text)
                    self.assertIn("Read", text)
                    self.assertIn("Grep", text)
                    self.assertIn("Glob", text)

    def test_install_hooks_dry_run_reports_claude_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            result = install_hooks.install(repo, "claude", dry_run=True)

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["target"].endswith(".claude\\settings.json") or result["target"].endswith(".claude/settings.json"))
        self.assertIn("hooks", result["planned_config"])
        command = result["planned_config"]["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        matcher = result["planned_config"]["hooks"]["PreToolUse"][0]["matcher"]
        self.assertIn("Update", matcher)
        self.assertIn(str(ROOT / "skills" / "e2e-dev-harness" / "scripts" / "phase_guard.py"), command)
        self.assertIn(str(repo), command)
        self.assertIn("--require-active-run-for-read", command)
        self.assertIn("--require-session-checkpoint", command)
        stop_command = result["planned_config"]["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertIn(str(ROOT / "skills" / "e2e-dev-harness" / "scripts" / "harness_stop_guard.py"), stop_command)
        self.assertIn(str(repo), stop_command)
        self.assertIn("--strict", stop_command)

    def test_install_hooks_rewrites_portable_runtime_templates(self) -> None:
        for runtime in ("codex", "gemini"):
            with self.subTest(runtime=runtime), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)

                result = install_hooks.install(repo, runtime, dry_run=True)
                command = result["planned_config"]["command"]

                self.assertTrue(result["ready"], result["blocked_reasons"])
                self.assertIn(str(ROOT / "skills" / "e2e-dev-harness" / "scripts" / "phase_guard.py"), command)
                self.assertIn("--require-active-run-for-read", command)
                self.assertIn(str(repo), command)
                self.assertNotIn("skills/e2e-dev-harness/scripts/phase_guard.py .", command)

    def test_install_hooks_installs_opencode_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            result = install_hooks.install(repo, "opencode")
            target = repo / ".opencode" / "plugins" / "e2e-dev-harness.js"
            validation = install_hooks.validate_config(target)
            text = target.read_text(encoding="utf-8")

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(validation["ready"], validation["blocked_reasons"])
        self.assertIn("tool.execute.before", text)
        self.assertIn(str(ROOT / "skills" / "e2e-dev-harness" / "scripts" / "phase_guard.py").replace("\\", "\\\\"), text)
        self.assertIn(str(repo).replace("\\", "\\\\"), text)
        self.assertIn("--require-active-run-for-read", text)
        self.assertIn("--require-session-checkpoint", text)

    def test_install_hooks_rejects_nonblocking_opencode_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target = repo / ".opencode" / "plugins" / "e2e-dev-harness.js"
            target.parent.mkdir(parents=True)
            target.write_text("export const X = { 'tool.execute.after': () => {} };\n", encoding="utf-8")

            result = install_hooks.validate_config(target)

        self.assertFalse(result["ready"])
        self.assertTrue(any("tool.execute.before" in reason for reason in result["blocked_reasons"]))

    def test_install_hooks_merges_claude_settings_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({"permissions": {"allow": ["Bash(git status)"]}}), encoding="utf-8")

            first = install_hooks.install(repo, "claude")
            second = install_hooks.install(repo, "claude")
            config = json.loads(settings.read_text(encoding="utf-8"))
            validation = install_hooks.validate_config(settings)

        self.assertTrue(first["ready"], first["blocked_reasons"])
        self.assertTrue(second["ready"], second["blocked_reasons"])
        self.assertTrue(validation["ready"], validation["blocked_reasons"])
        self.assertEqual(["Bash(git status)"], config["permissions"]["allow"])
        self.assertEqual(1, len(config["hooks"]["PreToolUse"]))
        self.assertEqual(1, len(config["hooks"]["Stop"]))

    def test_install_hooks_rejects_repo_relative_phase_guard_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "python skills/e2e-dev-harness/scripts/phase_guard.py . --hook-input - --json",
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = install_hooks.validate_config(settings)

        self.assertFalse(result["ready"])
        self.assertTrue(any("absolute path" in reason for reason in result["blocked_reasons"]))

    def test_install_hooks_rejects_wrong_installed_phase_guard_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            wrong_phase_guard = Path.home() / ".claude" / "skills" / "e2e-dev-harness" / "phase_guard.py"
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Read|Grep|Glob|Write|Edit|Update|MultiEdit|NotebookEdit|Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f'"{sys.executable}" "{wrong_phase_guard}" "{repo}" --hook-input - --require-active-run-for-read --require-session-checkpoint --json',
                                        }
                                    ],
                                }
                            ],
                            "Stop": [
                                {
                                    "matcher": "",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f'"{sys.executable}" "{ROOT / "skills" / "e2e-dev-harness" / "scripts" / "harness_stop_guard.py"}" "{repo}" --hook-input - --strict --json',
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = install_hooks.validate_config(settings)

        self.assertFalse(result["ready"])
        self.assertTrue(any("installed phase_guard.py" in reason for reason in result["blocked_reasons"]))

    def test_install_hooks_rejects_posttooluse_only_phase_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PostToolUse": [
                                {
                                    "matcher": "Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f'"{sys.executable}" "{ROOT / "skills" / "e2e-dev-harness" / "scripts" / "phase_guard.py"}" "{repo}" --hook-input - --require-active-run-for-read --json',
                                        }
                                    ],
                                }
                            ],
                            "Stop": [
                                {
                                    "matcher": "",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f'"{sys.executable}" "{ROOT / "skills" / "e2e-dev-harness" / "scripts" / "harness_stop_guard.py"}" "{repo}" --hook-input - --strict --json',
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = install_hooks.validate_config(settings)

        self.assertFalse(result["ready"])
        self.assertTrue(any("PreToolUse" in reason for reason in result["blocked_reasons"]))

    def test_install_hooks_rejects_missing_claude_stop_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Read|Grep|Glob|Task|Write|Edit|Update|MultiEdit|NotebookEdit|Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f"\"{sys.executable}\" \"{ROOT / 'skills' / 'e2e-dev-harness' / 'scripts' / 'phase_guard.py'}\" \"{repo}\" --hook-input - --require-active-run-for-read --require-session-checkpoint --json",
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = install_hooks.validate_config(settings)

        self.assertFalse(result["ready"])
        self.assertTrue(any("Stop hook" in reason for reason in result["blocked_reasons"]))

    def test_install_hooks_rejects_missing_claude_update_matcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Read|Grep|Glob|Task|Write|Edit|MultiEdit|NotebookEdit|Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f"\"{sys.executable}\" \"{ROOT / 'skills' / 'e2e-dev-harness' / 'scripts' / 'phase_guard.py'}\" \"{repo}\" --hook-input - --require-active-run-for-read --require-session-checkpoint --json",
                                        }
                                    ],
                                }
                            ],
                            "Stop": [
                                {
                                    "matcher": "",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f"\"{sys.executable}\" \"{ROOT / 'skills' / 'e2e-dev-harness' / 'scripts' / 'harness_stop_guard.py'}\" \"{repo}\" --hook-input - --json",
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = install_hooks.validate_config(settings)

        self.assertFalse(result["ready"])
        self.assertTrue(any("Update" in reason for reason in result["blocked_reasons"]))

    def test_install_hooks_rejects_missing_claude_task_matcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Read|Grep|Glob|Write|Edit|Update|MultiEdit|NotebookEdit|Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f"\"{sys.executable}\" \"{ROOT / 'skills' / 'e2e-dev-harness' / 'scripts' / 'phase_guard.py'}\" \"{repo}\" --hook-input - --require-active-run-for-read --require-session-checkpoint --json",
                                        }
                                    ],
                                }
                            ],
                            "Stop": [
                                {
                                    "matcher": "",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f"\"{sys.executable}\" \"{ROOT / 'skills' / 'e2e-dev-harness' / 'scripts' / 'harness_stop_guard.py'}\" \"{repo}\" --hook-input - --strict --json",
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = install_hooks.validate_config(settings)

        self.assertFalse(result["ready"])
        self.assertTrue(any("Task" in reason for reason in result["blocked_reasons"]))

    def test_install_hooks_rejects_unscoped_gateguard_fact_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Read|Grep|Glob|Task|Write|Edit|Update|MultiEdit|NotebookEdit|Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f"\"{sys.executable}\" \"{ROOT / 'skills' / 'e2e-dev-harness' / 'scripts' / 'phase_guard.py'}\" \"{repo}\" --hook-input - --require-active-run-for-read --require-session-checkpoint --json",
                                        }
                                    ],
                                },
                                {
                                    "matcher": "Write|Edit|Update|MultiEdit|Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "python gateguard-fact-force.py --all-writes",
                                        }
                                    ],
                                },
                            ],
                            "Stop": [
                                {
                                    "matcher": "",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f"\"{sys.executable}\" \"{ROOT / 'skills' / 'e2e-dev-harness' / 'scripts' / 'harness_stop_guard.py'}\" \"{repo}\" --hook-input - --strict --json",
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = install_hooks.validate_config(settings)

        self.assertFalse(result["ready"])
        self.assertTrue(any("gateguard-fact-force" in reason for reason in result["blocked_reasons"]))

    def test_install_hooks_rejects_non_strict_claude_stop_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Read|Grep|Glob|Task|Write|Edit|Update|MultiEdit|NotebookEdit|Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f"\"{sys.executable}\" \"{ROOT / 'skills' / 'e2e-dev-harness' / 'scripts' / 'phase_guard.py'}\" \"{repo}\" --hook-input - --require-active-run-for-read --require-session-checkpoint --json",
                                        }
                                    ],
                                }
                            ],
                            "Stop": [
                                {
                                    "matcher": "",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": f"\"{sys.executable}\" \"{ROOT / 'skills' / 'e2e-dev-harness' / 'scripts' / 'harness_stop_guard.py'}\" \"{repo}\" --hook-input - --json",
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = install_hooks.validate_config(settings)

        self.assertFalse(result["ready"])
        self.assertTrue(any("--strict" in reason for reason in result["blocked_reasons"]))

    def test_install_hooks_rewrites_stale_repo_relative_phase_guard_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "python skills/e2e-dev-harness/scripts/phase_guard.py . --hook-input - --json",
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = install_hooks.install(repo, "claude", dry_run=True)
            entries = result["planned_config"]["hooks"]["PreToolUse"]

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(1, len(entries))
        command = entries[0]["hooks"][0]["command"]
        self.assertIn(str(ROOT / "skills" / "e2e-dev-harness" / "scripts" / "phase_guard.py"), command)
        self.assertIn(str(repo), command)
        self.assertNotIn("python skills/e2e-dev-harness/scripts/phase_guard.py .", command)

    def test_pre_code_blocks_when_project_hook_config_is_broken(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "IMPLEMENTED")
            write_implemented_state(repo, state_path, state)
            settings = repo / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Read|Grep|Glob|Write|Edit|Update|MultiEdit|NotebookEdit|Bash",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": r"\python C:\Users\14907\.claude\skills\e2e-dev-harness\phase_guard.py . --hook-input - --require-active-run-for-read --require-session-checkpoint --json",
                                        }
                                    ],
                                }
                            ],
                            "Stop": [
                                {
                                    "matcher": "",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": r"\python C:\Users\14907\.claude\skills\e2e-dev-harness\phase_guard.py . --hook-input - --strict --json",
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            home = repo / "home"
            home.mkdir()
            args = SimpleNamespace(
                repo=repo,
                tool="Edit",
                path=[Path("services/payment-service/src/main/java/PaymentService.java")],
                patch=None,
                command_text="",
                lock=None,
                run_dir=Path("docs/agent-runs/run"),
                status_file=None,
            )

            with patch.object(e2e_dev_harness.Path, "home", return_value=home):
                code, result = e2e_dev_harness.pre_code(args)

        self.assertEqual(2, code)
        self.assertFalse(result["ready"])
        self.assertTrue(any("Runtime hook config is present but not enforcing" in reason for reason in result["blocked_reasons"]))

    def test_auto_transition_from_ready_gate_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            red = run_dir / "evidence" / "red-test.txt"
            status = run_dir / "evidence" / "implementation-gate.json"
            red.parent.mkdir(parents=True)
            red.write_text("expected failure\n", encoding="utf-8")
            status.write_text(json.dumps(implementation_gate_payload(red)), encoding="utf-8")
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = auto_transition.transition_from_status(repo, status, state_path)
            updated = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("transitioned", result["action"])
        self.assertEqual("IMPLEMENTED", updated["lifecycle"])
        self.assertEqual("passed", updated["gates"]["implementation"])

    def test_auto_transition_skips_unready_gate_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            status = run_dir / "evidence" / "implementation-gate.json"
            status.parent.mkdir(parents=True)
            status.write_text(json.dumps({"phase": "implementation", "ready": False}), encoding="utf-8")
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = auto_transition.transition_from_status(repo, status, state_path)
            updated = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("skipped", result["action"])
        self.assertEqual("PLANNED", updated["lifecycle"])

    def test_ci_template_documents_harness_verify(self) -> None:
        template = ROOT / "skills" / "e2e-dev-harness" / "ci" / "github-actions-harness.yml"
        text = template.read_text(encoding="utf-8")

        self.assertIn("e2e_dev_harness.py verify", text)
        self.assertIn("--harness", text)
        self.assertIn("HARNESS_RUN_STATE", text)

    def test_harness_policy_blocks_completed_run_without_reviews(self) -> None:
        registry = {
            "schema": "e2e-dev-harness.artifact-registry.v1",
            "selected_mode": "single",
            "services": ["services/order-service"],
            "artifacts": [
                {
                    "type": "requirements_archive",
                    "owner": "global",
                    "path": "docs/agent-runs/run/requirements-archive.md",
                    "status": "present",
                }
            ],
        }
        state = {
            "schema": "e2e-dev-harness.run-state.v1",
            "run_id": "run",
            "lifecycle": "VERIFIED",
            "selected_mode": "single",
            "services": ["services/order-service"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            result = harness_policy.validate_policy(repo, None, state, registry)

        self.assertFalse(result["ready"])
        self.assertTrue(any("R1 design review" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("R2 test review" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("R3 implementation review" in reason for reason in result["blocked_reasons"]))

    def test_harness_policy_cannot_disable_required_completion_reviews(self) -> None:
        registry = {
            "schema": "e2e-dev-harness.artifact-registry.v1",
            "selected_mode": "single",
            "services": ["services/order-service"],
            "artifacts": [
                {
                    "type": "requirements_archive",
                    "owner": "global",
                    "path": "docs/agent-runs/run/requirements-archive.md",
                    "status": "present",
                }
            ],
        }
        state = {
            "schema": "e2e-dev-harness.run-state.v1",
            "run_id": "run",
            "lifecycle": "VERIFIED",
            "selected_mode": "single",
            "services": ["services/order-service"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            policy = repo / ".e2e" / "harness-policy.json"
            policy.parent.mkdir(parents=True)
            policy.write_text(
                json.dumps(
                    {
                        "require_run_state": False,
                        "require_artifact_registry": False,
                        "require_semantic_reviews_on_completion": False,
                    }
                ),
                encoding="utf-8",
            )

            result = harness_policy.validate_policy(repo, policy, state, registry)

        self.assertTrue(result["policy"]["require_run_state"])
        self.assertTrue(result["policy"]["require_artifact_registry"])
        self.assertTrue(result["policy"]["require_semantic_reviews_on_completion"])
        self.assertFalse(result["ready"])
        self.assertTrue(any("R3 implementation review" in reason for reason in result["blocked_reasons"]))

    def test_harness_verify_replays_state_registry_and_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifact = repo / "docs" / "agent-runs" / "run" / "exec-plan.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("plan\n", encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "run",
                {"exec_plan": "docs/agent-runs/run/exec-plan.md"},
                "single",
                [],
            )
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            artifact_registry.write_registry(repo, registry_path, registry)
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json")
            run_state.write_state(repo, state_path, state)

            result = harness_verify.validate(repo, state_path)

        self.assertFalse(result["ready"])
        self.assertTrue(any("not VERIFIED" in reason for reason in result["blocked_reasons"]))

    def test_harness_verify_stops_when_run_state_cannot_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text("{", encoding="utf-8")

            result = harness_verify.validate(repo, state_path)

        self.assertFalse(result["ready"])
        self.assertIsNone(result["artifact_registry"])
        self.assertIsNone(result["policy"])
        self.assertTrue(any("Run state" in reason for reason in result["blocked_reasons"]))

    def test_run_summary_reports_missing_required_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifact = repo / "docs" / "agent-runs" / "run" / "exec-plan.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("plan\n", encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "run",
                {
                    "exec_plan": "docs/agent-runs/run/exec-plan.md",
                    "requirements": "docs/agent-runs/run/handoffs/01-requirements-clarifier.md",
                    "design_review": "docs/agent-runs/run/reviews/R1-design-review.md",
                },
                "single",
                [],
            )
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            artifact_registry.write_registry(repo, registry_path, registry)
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json")
            run_state.write_state(repo, state_path, state)

            summary = run_summary.build_summary(
                repo,
                state_path,
                {"ready": False, "blocked_reasons": ["R3 missing"], "warnings": ["hash warning"]},
            )

        self.assertEqual("e2e-dev-harness.run-summary.v1", summary["schema"])
        self.assertEqual(3, summary["artifact_count"])
        self.assertEqual(1, summary["blocked_count"])
        self.assertEqual(1, summary["warning_count"])
        self.assertIn("docs/agent-runs/run/handoffs/01-requirements-clarifier.md", summary["required_missing"])
        self.assertEqual("planned", summary["semantic_reviews"]["R1"])
        self.assertIn("Resolve harness verification blockers.", summary["next_actions"])

    def test_run_summary_blocks_corrupt_execution_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            run_dir.mkdir(parents=True)
            trace = run_dir / "execution-trace.json"
            trace.write_text("{not-json", encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "run",
                {"execution_trace": "docs/agent-runs/run/execution-trace.json"},
                "single",
                [],
            )
            registry_path = run_dir / "artifact-registry.json"
            state_path = run_dir / "run-state.json"
            artifact_registry.write_registry(repo, registry_path, registry)
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json")
            run_state.write_state(repo, state_path, state)

            summary = run_summary.build_summary(repo, state_path, {"ready": True, "blocked_reasons": [], "warnings": []})

        self.assertFalse(summary["ready"])
        self.assertEqual(1, summary["source_error_count"])
        self.assertTrue(any("Execution trace is invalid JSON" in reason for reason in summary["blocked_reasons"]))
        self.assertIn("Repair unreadable or invalid harness JSON artifacts before trusting the archive.", summary["next_actions"])

    def test_run_summary_blocks_corrupt_run_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text("{not-json", encoding="utf-8")

            summary = run_summary.build_summary(repo, state_path, {"ready": True, "blocked_reasons": [], "warnings": []})

        self.assertFalse(summary["ready"])
        self.assertEqual(1, summary["source_error_count"])
        self.assertTrue(any("Run state is invalid JSON" in reason for reason in summary["blocked_reasons"]))

    def test_harness_verify_writes_run_summary_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifact = repo / "docs" / "agent-runs" / "run" / "exec-plan.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("plan\n", encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "run",
                {"exec_plan": "docs/agent-runs/run/exec-plan.md"},
                "single",
                [],
            )
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            summary_json = Path("docs/agent-runs/run/run-summary.json")
            summary_md = Path("docs/agent-runs/run/run-summary.md")
            artifact_registry.write_registry(repo, registry_path, registry)
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json")
            run_state.write_state(repo, state_path, state)
            result = harness_verify.validate(repo, state_path)

            summary = harness_verify.write_summary_outputs(repo, state_path, result, summary_json, summary_md)

            written = json.loads((repo / summary_json).read_text(encoding="utf-8"))
            markdown_text = (repo / summary_md).read_text(encoding="utf-8")

        self.assertFalse(summary["ready"])
        self.assertEqual("run", written["run_id"])
        self.assertTrue(any("not VERIFIED" in reason for reason in written["blocked_reasons"]))
        self.assertIn("# Run Summary: run", markdown_text)

    def test_workflow_tier_auto_marks_messaging_cross_service_as_critical(self) -> None:
        design_text = "Publish a DMQ refund callback with topic, tag, group, and payload contract."
        facts = {"service_candidates": ["services/refund-service", "services/ledger-service"], "multi_service": True}
        dependency_report = {"dependencies": [{"kind": "dmq"}], "unresolved_questions": []}

        result = task_tier.evaluate("auto", design_text, facts, dependency_report)

        self.assertEqual("critical", result["tier"])
        self.assertIn("gitnexus-impact", result["required_gates"])
        self.assertIn("contracts", result["required_gates"])
        self.assertIn("strict-guard", result["required_gates"])

    def test_workflow_tier_auto_keeps_single_service_rest_endpoint_standard(self) -> None:
        design_text = "Add one REST API endpoint in order-service for an admin lookup screen."
        facts = {"service_candidates": ["services/order-service"], "multi_service": False}

        result = task_tier.evaluate("auto", design_text, facts, {"dependencies": []})

        self.assertEqual("standard", result["tier"])
        self.assertIn("r1-review", result["required_gates"])
        self.assertNotIn("contracts", result["required_gates"])
        self.assertNotIn("strict-guard", result["required_gates"])

    def test_workflow_tier_auto_marks_cross_service_http_api_as_critical(self) -> None:
        design_text = "Add a REST API client from order-service to payment-service."
        facts = {"service_candidates": ["services/order-service", "services/payment-service"], "multi_service": True}
        dependency_report = {
            "dependencies": [{"kind": "http", "source_service": "services/order-service"}],
            "unresolved_questions": [],
        }

        result = task_tier.evaluate("auto", design_text, facts, dependency_report)

        self.assertEqual("critical", result["tier"])
        self.assertIn("contracts", result["required_gates"])
        self.assertIn("strict-guard", result["required_gates"])

    def test_workflow_tier_auto_marks_chinese_payment_risk_control_as_critical(self) -> None:
        design_text = "统一支付风控系统：黑名单、商户评级、限额规则、观察模式、降级策略。"
        facts = {"service_candidates": ["jeepay-payment"], "multi_service": False}

        result = task_tier.evaluate("auto", design_text, facts, {"dependencies": []})

        self.assertEqual("critical", result["tier"])
        self.assertIn("gitnexus-impact", result["required_gates"])
        self.assertIn("strict-guard", result["required_gates"])

    def test_plan_archive_writes_registered_knowledge_graph_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "services" / "order-service" / "src" / "main").mkdir(parents=True)
            (repo / "services" / "order-service" / "pom.xml").write_text("<project />\n", encoding="utf-8")
            (repo / "pom.xml").write_text(
                "<project><modules><module>services/order-service</module></modules></project>\n",
                encoding="utf-8",
            )
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text("# Feature\n\n## Scope\n- services/order-service\n", encoding="utf-8")
            args = SimpleNamespace(
                repo=repo,
                mode="single",
                design_doc=Path("docs/design/feature.md"),
                agent_run_dir="docs/agent-runs/run",
                run_date="2026-05-31",
                service_scope="affected",
                service=["services/order-service"],
                path=None,
                dependency_report=None,
                create_archive=True,
                write_exec_plan=False,
                status_file=None,
            )

            code, result = e2e_dev_harness.plan(args)
            kg_path = repo / result["handoff_artifacts"]["knowledge_graph_status"]
            kg_exists = kg_path.exists()
            kg_status = json.loads(kg_path.read_text(encoding="utf-8"))

        self.assertEqual(0, code, result.get("blocked_reasons"))
        self.assertTrue(kg_exists)
        self.assertIn("selected_tools", kg_status)

    def test_implementation_gate_uses_run_state_registry_knowledge_graph_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            kg = run_dir / "evidence" / "knowledge-graph-refresh.json"
            kg.parent.mkdir(parents=True)
            kg.write_text(json.dumps({"selected_tools": ["gitnexus"], "available_tools": {"gitnexus": "gitnexus"}}), encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "docs/agent-runs/run",
                {
                    "run_state": "docs/agent-runs/run/run-state.json",
                    "artifact_registry": "docs/agent-runs/run/artifact-registry.json",
                    "knowledge_graph_status": "docs/agent-runs/run/evidence/knowledge-graph-refresh.json",
                },
                "single",
                [],
            )
            registry_path = run_dir / "artifact-registry.json"
            artifact_registry.write_registry(repo, registry_path, registry)
            state = run_state.build_state("docs/agent-runs/run", "single", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, run_dir / "run-state.json", state)

            result = implementation_gate.validate_gate_request(
                implementation_gate.GateRequest(
                    repo=repo,
                    phase="implementation",
                    run_state=Path("docs/agent-runs/run/run-state.json"),
                    tdd_mode="off",
                    require_semantic_reviews=False,
                    require_gitnexus_evidence="off",
                    workflow_tier="basic",
                )
            )

        self.assertFalse(any("Knowledge graph status file not found" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(result["knowledge_graph_status_loaded"])

    def test_workflow_tier_basic_still_keeps_harness_record(self) -> None:
        result = task_tier.evaluate("basic", "Update validation message.", {}, {})

        self.assertEqual("basic", result["tier"])
        self.assertIn("clarification", result["required_gates"])
        self.assertIn("impact-summary", result["required_gates"])
        self.assertIn("test-evidence", result["required_gates"])
        self.assertIn("task-alignment", result["required_gates"])
        self.assertIn("run-state", result["required_gates"])
        self.assertIn("artifact-registry", result["required_gates"])
        self.assertIn("run-summary", result["required_gates"])
        self.assertNotIn("r1-review", result["required_gates"])

    def test_prepare_reports_workflow_tier(self) -> None:
        facts = {
            "poms": ["pom.xml"],
            "root_modules": [],
            "spring_entrypoints": [],
            "spring_configs": [],
            "design_docs_or_media_count": 0,
            "design_docs_or_media_sample": [],
            "graphify_graph": "graphify-out/graph.json",
            "graphify_graph_exists": False,
            "service_candidates": ["services/payment-service", "services/ledger-service"],
            "multi_service": True,
        }
        dependency_result = {
            "ready": True,
            "tool_priority": ["gitnexus", "deterministic-scan", "graphify"],
            "dependencies": [{"kind": "http", "source_service": "services/payment-service"}],
            "unresolved_questions": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "refund.md"
            design.parent.mkdir(parents=True)
            design.write_text("Refund API updates payment state and calls ledger-service.", encoding="utf-8")
            args = SimpleNamespace(
                repo=repo,
                design_doc=Path("docs/design/refund.md"),
                path=None,
                service=None,
                agent_mode="off",
                agent_scope="auto",
                include_agent_content=False,
                max_agent_chars=12000,
                max_discovered_services=agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT,
                superpowers_mode="off",
                memory_mode="off",
                agent_orchestration_mode="off",
                service_scope="discovery",
                agent_run_dir=None,
                run_date="2026-05-23",
                kg_mode="auto",
                dependency_scan_mode="strict",
                write_dependency_report=False,
                dependency_output_dir=None,
                workflow_tier="auto",
                status_file=None,
            )
            with (
                patch.object(e2e_dev_harness.kg_refresh, "detect", return_value=facts),
                patch.object(e2e_dev_harness.cross_service_dependency_scan, "scan", return_value=dependency_result),
            ):
                code, result = e2e_dev_harness.prepare(args)

        self.assertEqual(0, code, result.get("blocked_reasons"))
        self.assertEqual("critical", result["workflow_tier"]["tier"])
        self.assertIn("contracts", result["workflow_tier"]["required_gates"])

    def test_verify_harness_replays_state_and_writes_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifact = repo / "docs" / "agent-runs" / "run" / "exec-plan.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("plan\n", encoding="utf-8")
            registry = artifact_registry.build_registry(
                repo,
                "run",
                {"exec_plan": "docs/agent-runs/run/exec-plan.md"},
                "single",
                [],
            )
            registry_path = repo / "docs" / "agent-runs" / "run" / "artifact-registry.json"
            state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
            summary_path = repo / "docs" / "agent-runs" / "run" / "run-summary.json"
            artifact_registry.write_registry(repo, registry_path, registry)
            state = run_state.build_state("run", "single", [], "docs/agent-runs/run/artifact-registry.json")
            run_state.write_state(repo, state_path, state)
            args = SimpleNamespace(
                repo=repo,
                design_doc=None,
                path=None,
                service=None,
                agent_mode="off",
                agent_scope="auto",
                include_agent_content=False,
                max_agent_chars=12000,
                max_discovered_services=agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT,
                superpowers_mode="off",
                memory_mode="off",
                agent_orchestration_mode="off",
                service_scope="discovery",
                agent_run_dir=None,
                run_date="2026-05-23",
                kg_mode="auto",
                dependency_scan_mode="off",
                write_dependency_report=False,
                dependency_output_dir=None,
                workflow_tier="basic",
                module=None,
                run_gate=False,
                phase="planning",
                kg_status_file=None,
                red_test_evidence=None,
                coverage_matrix=None,
                unit_test_evidence=None,
                business_review=None,
                memory_updates=None,
                requirements_archive=None,
                require_requirements_archive=False,
                dependency_report=None,
                implementation_manifest=None,
                rework_dir=None,
                review_dir=None,
                review_profile=None,
                handoff_dir=None,
                contract_dir=None,
                require_contracts=False,
                require_handoffs=False,
                require_semantic_reviews=False,
                skip_spring_static_check=False,
                skip_maven=True,
                strict_workflow=False,
                workflow_approval=None,
                harness=True,
                state=state_path,
                policy=None,
                strict_artifacts=False,
                run_completion_gate=False,
                summary_json=summary_path,
                summary_md=None,
                status_file=None,
            )

            code, result = e2e_dev_harness.verify(args)
            summary_exists = summary_path.exists()

        self.assertEqual(2, code, result)
        self.assertFalse(result["harness"]["ready"])
        self.assertTrue(any("not VERIFIED" in reason for reason in result["harness"]["blocked_reasons"]))
        self.assertTrue(summary_exists)

    def test_execution_trace_records_elapsed_and_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            trace = Path("docs/agent-runs/run/execution-trace.json")

            execution_trace.append_event(
                repo,
                trace,
                "r3-review",
                "finish",
                status="ready",
                elapsed_ms=120,
                input_tokens=1000,
                output_tokens=250,
                agent="reviewer-r3",
                decision="approved",
            )
            result = execution_trace.validate_trace(repo, trace, ["r3-review"])

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual(120, result["summary"]["elapsed_ms_total"])
        self.assertEqual(1250, result["summary"]["tokens"]["total"])

    def test_execution_trace_blocks_corrupt_json_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            trace = repo / "docs" / "agent-runs" / "run" / "execution-trace.json"
            trace.parent.mkdir(parents=True)
            trace.write_text("{not-json", encoding="utf-8")

            result = execution_trace.append_event(repo, trace.relative_to(repo), "verify", "finish")
            validation = execution_trace.validate_trace(repo, trace.relative_to(repo))
            trace_text = trace.read_text(encoding="utf-8")

        self.assertFalse(result["ready"])
        self.assertFalse(validation["ready"])
        self.assertIn("{not-json", trace_text)
        self.assertTrue(any("invalid JSON" in reason for reason in result["blocked_reasons"]))

    def test_verify_blocks_when_trace_file_is_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            trace_path = repo / "docs" / "agent-runs" / "run" / "execution-trace.json"
            trace_path.parent.mkdir(parents=True)
            trace_path.write_text("{not-json", encoding="utf-8")
            args = SimpleNamespace(
                repo=repo,
                design_doc=None,
                path=None,
                service=None,
                agent_mode="off",
                agent_scope="auto",
                include_agent_content=False,
                max_agent_chars=12000,
                max_discovered_services=agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT,
                superpowers_mode="off",
                memory_mode="off",
                agent_orchestration_mode="off",
                service_scope="discovery",
                agent_run_dir=None,
                run_date="2026-05-23",
                kg_mode="auto",
                dependency_scan_mode="off",
                write_dependency_report=False,
                dependency_output_dir=None,
                workflow_tier="basic",
                module=None,
                run_gate=False,
                phase="planning",
                kg_status_file=None,
                red_test_evidence=None,
                coverage_matrix=None,
                unit_test_evidence=None,
                business_review=None,
                memory_updates=None,
                requirements_archive=None,
                require_requirements_archive=False,
                dependency_report=None,
                implementation_manifest=None,
                changed_files=None,
                base_ref=None,
                rework_dir=None,
                review_dir=None,
                review_profile=None,
                handoff_dir=None,
                contract_dir=None,
                require_contracts=False,
                require_handoffs=False,
                require_semantic_reviews=False,
                skip_spring_static_check=False,
                run_state=None,
                skip_maven=True,
                strict_workflow=False,
                workflow_approval=None,
                harness=False,
                state=None,
                policy=None,
                strict_artifacts=False,
                run_completion_gate=False,
                summary_json=None,
                summary_md=None,
                status_file=None,
                trace_file=trace_path,
            )

            code, result = e2e_dev_harness.verify(args)
            trace_text = trace_path.read_text(encoding="utf-8")

        self.assertEqual(2, code)
        self.assertFalse(result["execution_trace"]["ready"])
        self.assertIn("{not-json", trace_text)

    def test_verify_writes_execution_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            trace_path = Path("docs/agent-runs/run/execution-trace.json")
            args = SimpleNamespace(
                repo=repo,
                design_doc=None,
                path=None,
                service=None,
                agent_mode="off",
                agent_scope="auto",
                include_agent_content=False,
                max_agent_chars=12000,
                max_discovered_services=agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT,
                superpowers_mode="off",
                memory_mode="off",
                agent_orchestration_mode="off",
                service_scope="discovery",
                agent_run_dir=None,
                run_date="2026-05-23",
                kg_mode="auto",
                dependency_scan_mode="off",
                write_dependency_report=False,
                dependency_output_dir=None,
                workflow_tier="basic",
                module=None,
                run_gate=False,
                phase="planning",
                kg_status_file=None,
                red_test_evidence=None,
                coverage_matrix=None,
                unit_test_evidence=None,
                business_review=None,
                memory_updates=None,
                requirements_archive=None,
                require_requirements_archive=False,
                dependency_report=None,
                implementation_manifest=None,
                changed_files=None,
                base_ref=None,
                rework_dir=None,
                review_dir=None,
                review_profile=None,
                handoff_dir=None,
                contract_dir=None,
                require_contracts=False,
                require_handoffs=False,
                require_semantic_reviews=False,
                skip_spring_static_check=False,
                run_state=None,
                skip_maven=True,
                strict_workflow=False,
                workflow_approval=None,
                harness=False,
                state=None,
                policy=None,
                strict_artifacts=False,
                run_completion_gate=False,
                summary_json=None,
                summary_md=None,
                status_file=None,
                trace_file=trace_path,
            )

            code, _result = e2e_dev_harness.verify(args)
            trace_result = execution_trace.validate_trace(repo, trace_path, ["prepare", "maven", "verify"])

        self.assertEqual(0, code, _result.get("blocked_reasons"))
        self.assertTrue(trace_result["ready"], trace_result["blocked_reasons"])
        self.assertGreaterEqual(trace_result["summary"]["elapsed_ms_total"], 0)

    def test_multi_agent_plan_splits_code_developers_by_service(self) -> None:
        artifacts = orchestration_plan.artifacts(
            "checkout",
            run_date="2026-05-23",
            services=["services/order-service", "services/payment-service"],
        )

        agents = orchestration_plan.agent_plan("multi", artifacts, ["services/order-service", "services/payment-service"])
        names = [agent["name"] for agent in agents]

        self.assertIn("code-developer-order-service", names)
        self.assertIn("code-developer-payment-service", names)
        self.assertIn("service-designer-order-service", names)
        self.assertIn("service-designer-payment-service", names)
        self.assertIn("test-case-developer-order-service", names)
        self.assertIn("test-case-developer-payment-service", names)
        self.assertIn("implementation-reviewer-order-service", names)
        self.assertIn("implementation-reviewer-payment-service", names)
        self.assertIn("coverage-reviewer", names)
        order_tdd = next(agent for agent in agents if agent["name"] == "test-case-developer-order-service")
        order_design = next(agent for agent in agents if agent["name"] == "service-designer-order-service")
        self.assertIn(artifacts["service_plans"]["services/order-service"]["service_design"], order_design["outputs"])
        self.assertIn(artifacts["service_plans"]["services/order-service"]["service_design"], order_tdd["inputs"])
        self.assertIn(artifacts["service_plans"]["services/order-service"]["red_test_evidence"], order_tdd["outputs"])
        order_developer = next(agent for agent in agents if agent["name"] == "code-developer-order-service")
        self.assertIn(artifacts["service_plans"]["services/order-service"]["red_test_evidence"], order_developer["inputs"])
        self.assertNotIn(
            artifacts["service_plans"]["services/order-service"]["implementation_review"],
            order_developer["outputs"],
        )

    def test_multi_agent_schedule_parallelizes_service_tdd_red_tasks(self) -> None:
        artifacts = orchestration_plan.artifacts(
            "checkout",
            run_date="2026-05-23",
            services=["services/order-service", "services/payment-service"],
        )

        agents = orchestration_plan.agent_plan("multi", artifacts, ["services/order-service", "services/payment-service"])
        schedule = orchestration_plan.agent_schedule("multi", ["services/order-service", "services/payment-service"], agents)
        tdd_tasks = [task for task in schedule["tasks"] if task["phase"] == "tdd-red" and task["service"]]
        groups = {task["parallel_group"] for task in tdd_tasks}

        self.assertEqual({"services/order-service", "services/payment-service"}, {task["service"] for task in tdd_tasks})
        self.assertEqual({"service:services/order-service", "service:services/payment-service"}, groups)
        self.assertTrue(all(task["depends_on_phases"] == ["design", "r1-review", "plan"] for task in tdd_tasks))

    def test_auto_mode_ignores_low_signal_api_message_words(self) -> None:
        body = "\n".join(
            f"Line {i}: The api endpoint emits an event message and uses a timeout."
            for i in range(80)
        )
        design_text = f"# Feature\n\n## Goal\nAdd one REST api endpoint.\n\n{body}"
        facts: dict = {"service_candidates": ["services/order-service"]}

        mode, reasons = orchestration_plan.choose_mode("auto", facts, design_text, False)

        self.assertEqual("single-review", mode, reasons)
        self.assertTrue(any("single-review floor" in reason for reason in reasons))

    def test_auto_mode_allows_single_with_machine_verified_low_risk_fact(self) -> None:
        design_text = "# Feature\n\nUpdate a display label."
        facts: dict = {
            "service_candidates": ["services/order-service"],
            "low_risk_single_service_approved": True,
        }

        mode, reasons = orchestration_plan.choose_mode("auto", facts, design_text, False)

        self.assertEqual("single", mode, reasons)
        self.assertTrue(any("machine-verified low-risk single-service" in reason for reason in reasons))

    def test_auto_mode_uses_single_review_for_single_service_risk_terms(self) -> None:
        design_text = textwrap.dedent(
            """
            # Payment Notice

            The payment service publishes a DMQ topic with a payload schema and requires idempotent retry.
            """
        )
        facts: dict = {"service_candidates": ["services/payment-service"]}

        mode, reasons = orchestration_plan.choose_mode("auto", facts, design_text, False)

        self.assertEqual("single-review", mode)
        self.assertTrue(any("risk keywords" in reason for reason in reasons))

    def test_auto_mode_uses_single_review_above_large_design_threshold(self) -> None:
        design_text = "# Large Feature\n\n" + ("x" * (orchestration_plan.LARGE_DESIGN_CHAR_THRESHOLD + 1))
        facts: dict = {"service_candidates": ["services/order-service"]}

        mode, reasons = orchestration_plan.choose_mode("auto", facts, design_text, False)

        self.assertEqual("single-review", mode)
        self.assertTrue(any("context isolation" in reason for reason in reasons))

    def test_auto_mode_triggers_multi_for_multiple_services_even_without_risk_terms(self) -> None:
        facts: dict = {"service_candidates": ["services/order-service", "services/payment-service"]}

        mode, reasons = orchestration_plan.choose_mode("auto", facts, "# Feature\n\nUpdate status fields.", False)

        self.assertEqual("multi", mode)
        self.assertTrue(any("multiple service" in reason for reason in reasons))

    def test_choose_mode_accepts_single_review(self) -> None:
        facts: dict = {"service_candidates": ["services/order-service"]}

        mode, reasons = orchestration_plan.choose_mode("single-review", facts, "irrelevant", False)

        self.assertEqual("single-review", mode)
        self.assertEqual(["mode explicitly set to single-review"], reasons)

    def test_single_review_escalates_to_multi_for_multiple_services(self) -> None:
        facts: dict = {"service_candidates": ["services/order-service", "services/payment-service"]}

        mode, reasons = orchestration_plan.choose_mode("single-review", facts, "irrelevant", False)

        self.assertEqual("multi", mode)
        self.assertTrue(any("single-review escalated" in reason for reason in reasons))

    def test_single_escalates_to_multi_for_multiple_services(self) -> None:
        facts: dict = {"service_candidates": ["services/order-service", "services/payment-service"]}

        mode, reasons = orchestration_plan.choose_mode("single", facts, "irrelevant", False)

        self.assertEqual("multi", mode)
        self.assertTrue(any("single escalated" in reason for reason in reasons))

    def test_single_escalates_to_single_review_for_single_service_risk_terms(self) -> None:
        facts: dict = {"service_candidates": ["services/payment-service"]}

        mode, reasons = orchestration_plan.choose_mode("single", facts, "payment risk control and retry", False)

        self.assertEqual("single-review", mode)
        self.assertTrue(any("single escalated to single-review" in reason for reason in reasons))

    def test_single_request_requires_low_risk_approval_to_stay_single(self) -> None:
        facts: dict = {"service_candidates": ["services/order-service"]}

        mode, reasons = orchestration_plan.choose_mode("single", facts, "# Feature\n\nUpdate status fields.", False)

        self.assertEqual("single-review", mode)
        self.assertTrue(any("single requires machine-verified low-risk approval" in reason for reason in reasons))

    def test_single_review_keeps_phase_reviewers_and_coverage_reviewer(self) -> None:
        artifacts = orchestration_plan.artifacts("checkout", run_date="2026-05-23")

        agents = orchestration_plan.agent_plan("single-review", artifacts, [])
        names = [agent["name"] for agent in agents]

        self.assertNotIn("single-agent", names)
        self.assertIn("requirements-clarifier", names)
        self.assertIn("use-case-designer", names)
        self.assertIn("test-case-developer", names)
        self.assertIn("code-developer", names)
        self.assertIn("single-reviewer-r1-design", names)
        self.assertIn("single-reviewer-r2-test", names)
        self.assertIn("single-reviewer-r3-implementation", names)
        self.assertIn("coverage-reviewer", names)
        schedule = orchestration_plan.agent_schedule("single-review", [], agents)
        groups = {task["agent"]: task["role_group"] for task in schedule["tasks"]}
        self.assertEqual("design", groups["requirements-clarifier"])
        self.assertEqual("test", groups["test-case-developer"])
        self.assertEqual("code", groups["code-developer"])
        phases = {task["agent"]: task["phase"] for task in schedule["tasks"]}
        self.assertEqual("r1-review", phases["single-reviewer-r1-design"])
        self.assertEqual("r2-review", phases["single-reviewer-r2-test"])
        self.assertEqual("r3-review", phases["single-reviewer-r3-implementation"])
        self.assertEqual("review", groups["single-reviewer-r2-test"])
        coverage = next(agent for agent in agents if agent["name"] == "coverage-reviewer")
        self.assertIn(artifacts["requirements_archive"], coverage["outputs"])

    def test_all_generated_modes_use_coordinator_only_execution_model(self) -> None:
        for mode, services in (
            ("single", []),
            ("single-review", []),
            ("multi", ["services/order-service", "services/payment-service"]),
        ):
            with self.subTest(mode=mode):
                artifacts = orchestration_plan.artifacts("checkout", None, None, services)
                agents = orchestration_plan.agent_plan(mode, artifacts, services)
                schedule = orchestration_plan.agent_schedule(mode, services, agents)

                self.assertEqual("dispatcher-confirmed", schedule["completion_mode"])
                self.assertEqual("coordinator-only-dispatch", schedule["execution_model"])
                self.assertIn("scheduling_decision", schedule)

    def test_agent_schedule_uses_declared_team_presets_for_capacity_metadata(self) -> None:
        bootstrap = orchestration_plan.agent_schedule(
            "bootstrap",
            [],
            [{"name": "requirements-clarifier", "inputs": [], "outputs": []}],
        )
        self.assertEqual("bootstrap", bootstrap["team_preset"])
        self.assertEqual(1, bootstrap["max_workers"])

        artifacts = orchestration_plan.artifacts("checkout", None, None, ["services/order-service"])
        agents = orchestration_plan.agent_plan("multi", artifacts, ["services/order-service"])
        multi = orchestration_plan.agent_schedule("multi", ["services/order-service"], agents)

        self.assertEqual("multi-service", multi["team_preset"])
        self.assertEqual(4, multi["max_workers"])
        self.assertEqual("dispatcher-confirmed", multi["completion_mode"])
        self.assertEqual("coordinator-only-dispatch", multi["execution_model"])
        self.assertEqual("service-parallel", multi["scheduling_decision"]["execution_model"])

    def test_plan_archive_writes_concrete_review_request_agent_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Goal
                    - Return a quote.

                    ## Scope
                    - services/sample-service

                    ## Use Cases
                    - Create quote.

                    ## Acceptance Criteria
                    - AC-1 Quote is returned.

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None
                    """
                ).strip(),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                repo=repo,
                mode="single-review",
                design_doc=Path("docs/design/feature.md"),
                agent_run_dir="docs/agent-runs/run",
                run_date="2026-05-31",
                path=["services/sample-service"],
                service=None,
                service_scope="affected",
                dependency_report=None,
                workflow_tier="auto",
                create_archive=True,
                write_exec_plan=None,
                status_file=None,
            )

            kg_facts = {"service_candidates": [], "multi_service": False, "design_docs_or_media_count": 1}
            kg_artifact = {"path": str(repo / "docs" / "agent-runs" / "run" / "evidence" / "knowledge-graph-refresh.json"), "status": {}}
            with patch.object(e2e_dev_harness.kg_refresh, "detect", return_value=kg_facts), \
                    patch.object(e2e_dev_harness, "write_kg_status_artifact", return_value=kg_artifact):
                code, result = e2e_dev_harness.plan(args)

            self.assertEqual(0, code, result)
            request_dir = repo / "docs" / "agent-runs" / "run" / "review-requests"
            expected_reviewers = {
                "R1-design-review-request.md": "single-reviewer-r1-design",
                "R2-test-review-request.md": "single-reviewer-r2-test",
                "R3-implementation-review-request.md": "single-reviewer-r3-implementation",
            }
            for file_name, reviewer_agent in expected_reviewers.items():
                text = (request_dir / file_name).read_text(encoding="utf-8")
                fields = reviewer_gate.parse_item(request_dir / file_name)
                self.assertNotIn("<developer-agent-id>", text)
                self.assertNotIn("<independent-reviewer-agent-id>", text)
                self.assertEqual("coordinator-agent", fields["developer_agent"])
                self.assertEqual(reviewer_agent, fields["reviewer_agent"])

    def test_dispatch_review_uses_invocation_path_declared_by_review_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            request = run_dir / "review-requests" / "R1-design-review-request.md"
            output = run_dir / "reviews" / "R1-design-review.md"
            declared_invocation = run_dir / "review-invocations" / "R1-design-review-invocation.json"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            request.parent.mkdir(parents=True)
            output.parent.mkdir(parents=True)
            request.write_text(
                textwrap.dedent(
                    """
                    # R1 Review Request

                    - Phase: design
                    - Reviewer Role: independent semantic reviewer
                    - Context Package: request-scoped; no inherited developer chat context
                    - Forbidden: inherited developer chat context; production-code edits; self-review
                    - Output: docs/agent-runs/run/reviews/R1-design-review.md
                    - Developer Agent: coordinator-agent
                    - Reviewer Agent: design-reviewer
                    - Reviewer Invocation: docs/agent-runs/run/review-invocations/R1-design-review-invocation.json
                    """
                ).strip(),
                encoding="utf-8",
            )
            schedule.parent.mkdir(parents=True, exist_ok=True)
            schedule.write_text(
                json.dumps(
                    {
                        "schema": "e2e-dev-harness.agent-schedule.v1",
                        "tasks": [
                            {
                                "id": "T01",
                                "agent": "design-reviewer",
                                "phase": "r1-review",
                                "role_group": "review",
                                "inputs": ["docs/agent-runs/run/review-requests/R1-design-review-request.md"],
                                "outputs": ["docs/agent-runs/run/reviews/R1-design-review.md"],
                                "status": "planned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state = run_state.build_state("docs/agent-runs/run", "single-review", [], "docs/agent-runs/run/artifact-registry.json", "PLANNED")
            run_state.write_state(repo, state_path, state)

            result = dispatcher.dispatch_next(repo, schedule, state_path)

            self.assertTrue(result["ready"], result)
            self.assertEqual("docs/agent-runs/run/review-invocations/R1-design-review-invocation.json", result["invocation_path"])
            self.assertTrue(declared_invocation.exists())

    def test_orchestration_plan_cli_accepts_single_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            facts = {
                "service_candidates": ["services/order-service"],
                "multi_service": False,
                "design_docs_or_media_count": 0,
                "spring_entrypoints": [],
            }

            with patch.object(orchestration_plan, "detect", return_value=facts), \
                    patch.object(
                        sys,
                        "argv",
                        [
                            "orchestration_plan.py",
                            str(repo),
                            "--mode",
                            "single-review",
                            "--service-scope",
                            "affected",
                            "--service",
                            "services/order-service",
                            "--json",
                        ],
                    ), \
                    patch("sys.stdout", new_callable=io.StringIO) as stdout:
                exit_code = orchestration_plan.main()

            result = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertEqual("single-review", result["selected_mode"])
        self.assertIn("coverage-reviewer", [agent["name"] for agent in result["agents"]])


class DispatchWaveCheckpointCadenceTest(unittest.TestCase):
    """#1: an unscaled per-session dispatch-wave signal that hard-blocks dispatch."""

    def _state(self, repo: Path) -> tuple[Path, dict]:
        state_path = repo / "docs" / "agent-runs" / "run" / "run-state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state = run_state.build_state(
            "docs/agent-runs/run",
            "multi",
            [],
            "docs/agent-runs/run/artifact-registry.json",
            "PLANNED",
        )
        return state_path, state

    def test_context_budget_flags_dispatch_waves_unscaled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path, state = self._state(repo)
            # A large schedule scales the chatty phase/tool ceilings, but the
            # dispatch-wave ceiling must stay unscaled so it is a real signal.
            (state_path.parent / "agent-schedule.json").write_text(
                json.dumps({"tasks": [{"id": f"T{i:02d}", "status": "planned"} for i in range(29)]}),
                encoding="utf-8",
            )
            state["dispatch_waves_since_checkpoint"] = 5
            run_state.write_state(repo, state_path, state)

            budget = session_checkpoint.context_budget(state_path, state)

        self.assertEqual(budget["metrics"]["dispatch_waves_since_checkpoint"], 5)
        self.assertEqual(budget["limits"]["max_dispatch_waves_since_checkpoint"], 4)
        self.assertIn("dispatch_waves_since_checkpoint", budget["exceeded_limits"])
        self.assertTrue(budget["handoff_recommended"])

    def test_dispatch_wave_counter_does_not_trip_below_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path, state = self._state(repo)
            state["dispatch_waves_since_checkpoint"] = 2
            run_state.write_state(repo, state_path, state)

            budget = session_checkpoint.context_budget(state_path, state)

        self.assertNotIn("dispatch_waves_since_checkpoint", budget["exceeded_limits"])

    def test_context_budget_adds_direct_tool_metrics_without_changing_existing_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path, state = self._state(repo)
            run_state.write_state(repo, state_path, state)
            cli_response = state_path.parent / "evidence" / "cli-responses" / "next.json"
            cli_response.parent.mkdir(parents=True, exist_ok=True)
            cli_response.write_text("{}", encoding="utf-8")
            tool_event = state_path.parent / "coordinator-tool-events" / "event.json"
            tool_event.parent.mkdir(parents=True, exist_ok=True)
            tool_event.write_text(
                json.dumps(
                    {
                        "tool": "Bash",
                        "classification": "blocked_high_output_shell",
                        "command_sha256": "a" * 64,
                        "paths": [],
                        "created_at": "2026-06-06T00:01:00Z",
                        "checkpoint_created_at": "2026-06-06T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            budget = session_checkpoint.context_budget(state_path, state)

        self.assertEqual(1, budget["metrics"]["tool_calls"])
        self.assertEqual(1, budget["metrics"]["direct_tool_calls_since_checkpoint"])
        self.assertEqual(1, budget["metrics"]["coordinator_tool_events"])
        self.assertEqual(1, budget["metrics"]["high_output_shell_blocks_since_checkpoint"])
        self.assertNotIn("direct_tool_calls_since_checkpoint", budget["exceeded_limits"])
        self.assertNotIn("high_output_shell_blocks_since_checkpoint", budget["exceeded_limits"])

    def test_update_dispatches_state_increments_wave_counter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path, state = self._state(repo)
            run_state.write_state(repo, state_path, state)

            dispatch = {"status": "awaiting_runtime_spawn", "current_task_id": "T01"}
            dispatcher.update_dispatches_state(repo, state_path, dispatch, {"T01": dispatch})
            reloaded = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(reloaded["dispatch_waves_since_checkpoint"], 1)

            dispatcher.update_dispatches_state(repo, state_path, dispatch, {"T02": dispatch})
            reloaded = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(reloaded["dispatch_waves_since_checkpoint"], 2)

    def test_session_checkpoint_create_resets_wave_counter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path, state = self._state(repo)
            state["dispatch_waves_since_checkpoint"] = 3
            run_state.write_state(repo, state_path, state)

            session_checkpoint.create(repo, state_path, {"phase": "tdd-red"})

            reloaded = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(reloaded["dispatch_waves_since_checkpoint"], 0)

    def test_dispatch_budget_gate_blocks_when_waves_exceed_without_fresh_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state_path, state = self._state(repo)
            state["dispatch_waves_since_checkpoint"] = 6
            run_state.write_state(repo, state_path, state)

            gate = coordinator_flow.dispatch_context_budget_gate(repo, state_path)

        self.assertFalse(gate["ready"])
        self.assertTrue(
            any("session checkpoint" in reason.lower() for reason in gate["blocked_reasons"]),
            gate["blocked_reasons"],
        )


class ReviewerSubagentTypeTest(unittest.TestCase):
    """#3: route review/coverage tasks to a specialized reviewer subagent type."""

    ROLE_DEFAULTS = PhaseFunctionTests.ROLE_DEFAULTS

    def _spawn(self, repo: Path, task: dict) -> dict:
        caps = dispatcher.runtime_capabilities("claude-code")
        return dispatcher.spawn_request_for_runtime(
            caps, task, "prompt body", repo / "agent-schedule.json", repo / "run-state.json", repo
        )

    def test_spawn_request_honors_task_runtime_subagent_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            task = {"id": "T05", "agent": "r2-reviewer", "phase": "r2-review", "runtime_subagent_type": "code-reviewer"}
            request = self._spawn(repo, task)
        self.assertEqual(request["tool"], "Task")
        self.assertEqual(request["arguments"]["subagent_type"], "code-reviewer")

    def test_spawn_request_derives_subagent_type_from_known_phase_when_task_field_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            task = {"id": "T01", "agent": "requirements-clarifier", "phase": "clarify"}
            request = self._spawn(repo, task)
        self.assertEqual(request["arguments"]["subagent_type"], "general-purpose")
        self.assertEqual(request["requested_subagent_type"], "requirements-clarifier")

    def test_claude_spawn_request_projects_harness_role_alias_to_portable_task_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            task = {
                "id": "T01",
                "agent": "requirements-clarifier",
                "phase": "clarify",
                "runtime_subagent_type": "requirements-clarifier",
            }
            request = self._spawn(repo, task)
        self.assertEqual(request["tool"], "Task")
        self.assertEqual(request["arguments"]["subagent_type"], "general-purpose")
        self.assertEqual(request["requested_subagent_type"], "requirements-clarifier")
        self.assertIn("requirements-clarifier", request["subagent_type_note"])

    def test_claude_spawn_request_honors_phase_subagent_env_override_after_schedule_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            task = {
                "id": "T01",
                "agent": "requirements-clarifier",
                "phase": "clarify",
                "runtime_subagent_type": "requirements-clarifier",
            }
            with patch.dict(os.environ, {"E2E_HARNESS_SUBAGENT_TYPE_CLARIFY": "Plan"}, clear=False):
                request = self._spawn(repo, task)
        self.assertEqual(request["arguments"]["subagent_type"], "Plan")
        self.assertEqual(request["requested_subagent_type"], "requirements-clarifier")

    def test_spawn_request_defaults_unknown_phase_subagent_type_to_general_purpose(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            task = {"id": "T99", "agent": "unknown-worker", "phase": "unknown-phase"}
            request = self._spawn(repo, task)
        self.assertEqual(request["arguments"]["subagent_type"], "general-purpose")

    def test_agent_schedule_routes_reviews_to_reviewer_subagent_when_env_set(self) -> None:
        artifacts = orchestration_plan.artifacts("checkout", run_date="2026-05-23")
        agents = orchestration_plan.agent_plan("single-review", artifacts, [])
        with patch.dict(
            orchestration_plan.os.environ,
            {"E2E_HARNESS_REVIEWER_SUBAGENT_TYPE": "code-reviewer"},
            clear=False,
        ):
            schedule = orchestration_plan.agent_schedule("single-review", [], agents)
        by_phase = {task["phase"]: task for task in schedule["tasks"]}
        for review_phase in ("r1-review", "r2-review", "r3-review"):
            self.assertEqual("code-reviewer", by_phase[review_phase]["runtime_subagent_type"], review_phase)
        # Non-review work follows its role declaration.
        self.assertEqual("implementation-planner", by_phase["plan"]["runtime_subagent_type"])

    def test_agent_schedule_defaults_to_role_declared_subagent_type_without_env(self) -> None:
        artifacts = orchestration_plan.artifacts("checkout", run_date="2026-05-23")
        agents = orchestration_plan.agent_plan("single-review", artifacts, [])
        with patch.dict(orchestration_plan.os.environ, {"E2E_HARNESS_REVIEWER_SUBAGENT_TYPE": ""}, clear=False):
            schedule = orchestration_plan.agent_schedule("single-review", [], agents)
        for task in schedule["tasks"]:
            self.assertEqual(self.ROLE_DEFAULTS[task["phase"]], task["runtime_subagent_type"], task["phase"])


class SchedulingDecisionProjectionTests(unittest.TestCase):
    def test_agent_schedule_explicit_empty_decision_preserves_team_preset(self) -> None:
        artifacts = orchestration_plan.artifacts(
            "feature",
            None,
            "2026-06-06",
            ["services/order-service"],
        )
        agents = orchestration_plan.agent_plan(
            "multi",
            artifacts,
            ["services/order-service"],
        )

        schedule = orchestration_plan.agent_schedule(
            "multi",
            ["services/order-service"],
            agents,
            scheduling_decision={},
        )

        self.assertEqual("coordinator-only-dispatch", schedule["execution_model"])
        self.assertEqual(4, schedule["max_workers"])

    def test_agent_schedule_includes_scheduling_decision_when_supplied(self) -> None:
        artifacts = orchestration_plan.artifacts(
            "feature",
            None,
            "2026-06-06",
            ["services/order-service"],
        )
        agents = orchestration_plan.agent_plan(
            "single-review",
            artifacts,
            ["services/order-service"],
        )
        decision = {
            "schema": "e2e-dev-harness.scheduling-decision.v1",
            "execution_model": "split-single",
            "max_workers": 2,
            "parallelism": {"code": "gated-by-edit-scope"},
        }

        schedule = orchestration_plan.agent_schedule(
            "single-review",
            ["services/order-service"],
            agents,
            scheduling_decision=decision,
        )

        self.assertEqual(decision, schedule["scheduling_decision"])
        self.assertEqual(1, schedule["max_workers"])
        self.assertEqual("coordinator-only-dispatch", schedule["execution_model"])


class SplitSingleServiceLaneTests(unittest.TestCase):
    def test_task_scheduling_metadata_normalizes_acceptance_ids(self) -> None:
        task = {"phase": "implement"}
        decision = {
            "execution_model": "split-single",
            "task_split": {
                "strategy": "acceptance-criteria",
                "acceptance_ids": "AC-1",
            },
            "parallelism": {"code": "gated-by-edit-scope"},
        }

        self.assertEqual(
            [],
            orchestration_plan.task_scheduling_metadata(task, decision)["acceptance_ids"],
        )

        decision["task_split"]["acceptance_ids"] = ["AC-1", 2, None]

        self.assertEqual(
            ["AC-1", "2", "None"],
            orchestration_plan.task_scheduling_metadata(task, decision)["acceptance_ids"],
        )

    def test_split_single_schedule_marks_code_task_as_scope_gated(self) -> None:
        artifacts = orchestration_plan.artifacts(
            "feature",
            None,
            "2026-06-06",
            ["services/order-service"],
        )
        agents = orchestration_plan.agent_plan(
            "single-review",
            artifacts,
            ["services/order-service"],
        )
        decision = scheduling_strategy.decide(
            "single-review",
            ["services/order-service"],
            ["large or design-heavy implementation context"],
            "## Acceptance Criteria\n- AC-1: Validate.\n- AC-2: Persist.\n",
        )

        schedule = orchestration_plan.agent_schedule(
            "single-review",
            ["services/order-service"],
            agents,
            scheduling_decision=decision,
        )
        code_tasks = [task for task in schedule["tasks"] if task["phase"] == "implement"]

        self.assertEqual(1, len(code_tasks))
        self.assertEqual(
            "gated-by-edit-scope",
            code_tasks[0]["scheduling"]["code_parallelism"],
        )
        self.assertEqual(
            ["AC-1", "AC-2"],
            code_tasks[0]["scheduling"]["acceptance_ids"],
        )
        self.assertTrue(code_tasks[0]["scheduling"]["requires_scope_partition"])


class DispatcherJsonOutputTest(unittest.TestCase):
    """Regression: `dispatcher.py --json` must emit valid JSON, not raise NameError."""

    def test_main_json_flag_prints_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            stdout = io.StringIO()
            argv = [
                "dispatcher.py",
                str(repo),
                "--action",
                "status",
                "--schedule",
                str(repo / "missing-schedule.json"),
                "--state",
                str(repo / "missing-state.json"),
                "--json",
            ]
            with patch.object(sys, "argv", argv), patch("sys.stdout", stdout):
                exit_code = dispatcher.main()
        payload = json.loads(stdout.getvalue())
        self.assertIsInstance(payload, dict)
        self.assertIn("ready", payload)
        # Exit code must stay consistent with the emitted JSON result.
        self.assertEqual(0 if payload["ready"] else 2, exit_code)


if __name__ == "__main__":
    unittest.main()
