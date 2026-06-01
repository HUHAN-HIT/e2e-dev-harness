"""Unified CLI integration tests."""
from __future__ import annotations

import sys
import io
import hashlib
import json
import os
import subprocess
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

import e2e_dev_harness  # noqa: E402
import run_state  # noqa: E402
import install_hooks  # noqa: E402

from conftest import REVIEW_CHECKLIST, write_command_evidence  # noqa: E402
import agent_instructions  # noqa: E402


class UnifiedCliTests(unittest.TestCase):
    REVIEW_CHECKLIST = REVIEW_CHECKLIST

    def write_role_template(self, repo: Path, path: Path) -> None:
        full = repo / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(
            textwrap.dedent(
                """
                # Role

                ## Role Boundary
                Own exactly one scheduled task.

                ## Allowed Inputs
                Use only context pack inputs.

                ## Forbidden
                Do not inherit coordinator chat context.

                ## Required Outputs
                Write only scheduled outputs.

                ## Done When
                Return evidence paths.
                """
            ).strip(),
            encoding="utf-8",
        )

    def write_ready_handoff(self, repo: Path, path: Path, agent_id: str = "requirements-agent") -> None:
        full = repo / path
        full.parent.mkdir(parents=True, exist_ok=True)
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
                  - {path.as_posix()}
                input_hashes:
                  - user-request sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
                output_hashes:
                  - {path.as_posix()} sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
                consumed_by:
                  - code-developer
                open_questions: None
                ready_at: 2026-05-23T00:00:00Z
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

    def default_review_checklist(self, phase: str) -> str:
        return "\n".join(f"- [x] {item}: checked." for item in self.REVIEW_CHECKLIST.get(phase, []))

    def write_semantic_reviews(self, repo: Path) -> Path:
        review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
        request_dir = repo / "docs" / "agent-runs" / "run" / "review-requests"
        invocation_dir = repo / "docs" / "agent-runs" / "run" / "review-invocations"
        review_dir.mkdir(parents=True, exist_ok=True)
        request_dir.mkdir(parents=True, exist_ok=True)
        invocation_dir.mkdir(parents=True, exist_ok=True)
        for phase, review_name, request_name in (
            ("design", "R1-design-review.md", "R1-design-review-request.md"),
            ("test", "R2-test-review.md", "R2-test-review-request.md"),
            ("implementation", "R3-implementation-review.md", "R3-implementation-review-request.md"),
        ):
            request_path = request_dir / request_name
            invocation_path = invocation_dir / f"{phase}-reviewer-invocation.json"
            request_path.write_text(
                textwrap.dedent(
                    f"""
                    # {phase.title()} Review Request

                    - Phase: {phase}
                    - Reviewer Role: independent semantic reviewer
                    - Context Package: request-scoped; no inherited developer chat context
                    - Allowed Inputs: design, tests, implementation refs, dependency report
                    - Forbidden: inherited developer chat context; production-code edits; self-review
                    - Output: docs/agent-runs/run/reviews/{review_name}
                    - Developer Agent: developer-agent-1
                    - Reviewer Agent: reviewer-agent-{phase}
                    - Reviewer Invocation: docs/agent-runs/run/review-invocations/{phase}-reviewer-invocation.json
                    """
                ).strip(),
                encoding="utf-8",
            )
            invocation_path.write_text(
                json.dumps(
                    {
                        "runtime": "claude-code",
                        "invocation_type": "subagent",
                        "developer_agent": "developer-agent-1",
                        "developer_session": "developer-session-1",
                        "reviewer_agent": f"reviewer-agent-{phase}",
                        "reviewer_session": f"reviewer-session-{phase}",
                        "context_pack": f"docs/agent-runs/run/review-requests/{request_name}",
                        "review_request": f"docs/agent-runs/run/review-requests/{request_name}",
                        "output": f"docs/agent-runs/run/reviews/{review_name}",
                        "fork_context": False,
                        "context_policy": "request-scoped; no-inherited-developer-chat-context",
                        "status": "completed",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            request_hash = hashlib.sha256(request_path.read_bytes()).hexdigest()
            checklist = self.default_review_checklist(phase)
            code_path_trace = ""
            if phase == "implementation":
                code_path_trace = textwrap.dedent(
                    """

                    ## Code Path Trace

                    - AC-1: Controller -> ApplicationService -> Repository/Client/Sender -> response or event.
                    - AC-2: Controller -> ApplicationService -> Validator/Repository -> error or state update.
                    - AC-3: Controller -> ApplicationService -> Repository/Client/Sender -> verified behavior.
                    - AC-4: Controller -> ApplicationService -> Repository/Client/Sender -> verified behavior.
                    - AC-5: Controller -> ApplicationService -> Repository/Client/Sender -> verified behavior.
                    """
                )
            (review_dir / review_name).write_text(
                textwrap.dedent(
                    f"""
                    # {phase.title()} Review

                    - Phase: {phase}
                    - Reviewer: semantic-reviewer
                    - Review Request: docs/agent-runs/run/review-requests/{request_name}
                    - Developer Agent: developer-agent-1
                    - Reviewer Agent: reviewer-agent-{phase}
                    - Reviewer Session: reviewer-session-{phase}
                    - Reviewer Invocation: docs/agent-runs/run/review-invocations/{phase}-reviewer-invocation.json
                    - Request Hash: {request_hash}
                    - Independence: independent-agent
                    - Context Boundary: request-scoped; no inherited developer chat context
                    - No Code Changes: confirmed
                    - Scope: all-services
                    - Inputs Reviewed: requirements; use cases; tests; implementation refs
                    - Findings: None
                    - Required Rework: None
                    - Status: approved

                    ## Required Review Checklist

                    {checklist}
                    {code_path_trace}
                    """
                ).strip(),
                encoding="utf-8",
            )
        return review_dir

    def test_align_prepare_scopes_warns_when_explicit_scopes_differ(self) -> None:
        agent_scope, service_scope, notes = e2e_dev_harness.align_prepare_scopes("discovery", "affected")

        self.assertEqual("discovery", agent_scope)
        self.assertEqual("affected", service_scope)
        self.assertTrue(any("differ" in note for note in notes))

    def test_pyproject_exposes_short_cli_alias(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn("e2eh = \"e2e_dev_harness:main\"", pyproject)

    def test_clarify_cli_emits_utf8_json_on_windows_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Goal
                    - Add risk control.

                    ## Scope
                    - Affected services/modules: payment

                    ## Use Cases
                    - UC-1: User submits a payment.

                    ## Acceptance Criteria
                    - AC-1: 是否需要支持 Aliyun RocketMQ 供应商？

                    ## Test Design
                    - First red test: RiskControlServiceTest

                    ## Impact Summary
                    - Source: manual non-applicability evidence
                    - Raw Evidence: docs/agent-runs/run/evidence/manual-impact.json

                    | type | interface | affected callers/consumers | related AC | required tests/contracts | risk |
                    | --- | --- | --- | --- | --- | --- |
                    | manual | payment | controller | AC-1 | unit | low |

                    ## Change Logic
                    - Current behavior: no risk control.
                    - Target behavior: add risk control.
                    - Runtime path: Controller -> Service -> Repository.
                    - State/data/API/event effects: database state changes.

                    ## Open Questions
                    - Q1: 是否需要支持 Aliyun RocketMQ 供应商？
                    """
                ).strip(),
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "cp936"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "e2e_dev_harness.py"),
                    "clarify",
                    str(repo),
                    "--design-doc",
                    "docs/design/feature.md",
                    "--json-full",
                ],
                cwd=str(repo),
                env=env,
                capture_output=True,
            )
            output = completed.stdout.decode("utf-8")
            payload = json.loads(output)

        self.assertEqual(2, completed.returncode)
        self.assertIn("是否需要支持 Aliyun RocketMQ 供应商", payload["unresolved_open_questions"][0])

    def test_main_defaults_to_compact_stdout_and_writes_full_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            state = e2e_dev_harness.run_state.build_state(
                "docs/agent-runs/run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            e2e_dev_harness.run_state.write_state(repo, state_path, state)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "e2e_dev_harness.py"),
                    "next",
                    str(repo),
                    "--state",
                    str(state_path),
                    "--runtime",
                    "claude-code",
                ],
                cwd=str(repo),
                text=True,
                capture_output=True,
                check=False,
            )
            payload = json.loads(completed.stdout)
            full_path = Path(payload["full_result_path"])
            if not full_path.is_absolute():
                full_path = repo / full_path
            full = json.loads(full_path.read_text(encoding="utf-8"))

        self.assertEqual(0, completed.returncode)
        self.assertEqual("compact", payload["stdout_mode"])
        self.assertIn("full_result_path", payload)
        self.assertIn("coordinator_summary_path", payload)
        self.assertNotIn("workflow_plan", payload)
        self.assertNotIn("gates", payload)
        self.assertIn("workflow_plan", full)

    def test_main_json_full_preserves_complete_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            state = e2e_dev_harness.run_state.build_state(
                "docs/agent-runs/run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            e2e_dev_harness.run_state.write_state(repo, state_path, state)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "e2e_dev_harness.py"),
                    "next",
                    str(repo),
                    "--state",
                    str(state_path),
                    "--runtime",
                    "claude-code",
                    "--json-full",
                ],
                cwd=str(repo),
                text=True,
                capture_output=True,
                check=False,
            )
            payload = json.loads(completed.stdout)

        self.assertEqual(0, completed.returncode)
        self.assertIn("workflow_plan", payload)
        self.assertNotIn("stdout_mode", payload)

    def test_main_status_file_is_reported_as_full_result_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            state_path = run_dir / "run-state.json"
            status_file = run_dir / "custom-status.json"
            state = e2e_dev_harness.run_state.build_state(
                "docs/agent-runs/run",
                "single",
                [],
                "docs/agent-runs/run/artifact-registry.json",
                "PLANNED",
            )
            e2e_dev_harness.run_state.write_state(repo, state_path, state)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "e2e_dev_harness.py"),
                    "next",
                    str(repo),
                    "--state",
                    str(state_path),
                    "--status-file",
                    str(status_file),
                ],
                cwd=str(repo),
                text=True,
                capture_output=True,
                check=False,
            )
            payload = json.loads(completed.stdout)
            status_exists = status_file.exists()

        self.assertEqual(0, completed.returncode)
        self.assertEqual(str(status_file), payload["full_result_path"])
        self.assertTrue(status_exists)

    def test_install_command_full_defaults_to_current_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            source_skill = ROOT / "skills" / "e2e-dev-harness"
            args = SimpleNamespace(
                repo=repo,
                target="all",
                install_root=repo / "home",
                source_skill_dir=source_skill,
                runtime="claude",
                full=True,
                yes=False,
                install_external=False,
                skip_external=True,
                with_hooks=False,
                doctor=False,
                status_file=None,
            )

            code, result = e2e_dev_harness.install_project(args)

        self.assertEqual(0, code, result)
        self.assertEqual(str(repo.resolve()), result["project_root"])
        self.assertFalse(result["executed"])
        self.assertEqual(["codex", "claude", "agents"], result["targets"])
        self.assertIn("copy-skill", [action["id"] for action in result["actions"]])

    def test_next_cli_quiet_default_writes_full_result_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _code, start_result = e2e_dev_harness.start(
                SimpleNamespace(
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
            )

            stdout = io.StringIO()
            with patch.object(
                sys,
                "argv",
                [
                    "e2e_dev_harness.py",
                    "next",
                    str(repo),
                    "--state",
                    str(start_result["run_state"]),
                ],
            ), patch("sys.stdout", stdout):
                exit_code = e2e_dev_harness.main()
            payload = json.loads(stdout.getvalue())
            full_path = repo / payload["full_result_path"]
            full_path_exists = full_path.exists()
            full_payload = json.loads(full_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertIn("full_result_path", payload)
        self.assertIn("checkpoint", payload)
        self.assertIn("resume_instruction", payload)
        self.assertNotIn("workflow_plan", payload)
        self.assertNotIn("todo_policy", payload)
        self.assertTrue(full_path_exists)
        self.assertIn("workflow_plan", full_payload)
        self.assertIn("todo_policy", full_payload)

    def test_next_cli_quiet_surfaces_coordinator_context_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _code, start_result = e2e_dev_harness.start(
                SimpleNamespace(
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
            )
            state_path = repo / start_result["run_state"]
            evidence_dir = state_path.parent / "evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "large.md").write_text(
                "x" * (e2e_dev_harness.session_checkpoint.DEFAULT_MAX_EVIDENCE_BYTES + 1),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with patch.object(
                sys,
                "argv",
                [
                    "e2e_dev_harness.py",
                    "next",
                    str(repo),
                    "--state",
                    str(start_result["run_state"]),
                ],
            ), patch("sys.stdout", stdout):
                exit_code = e2e_dev_harness.main()
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["coordinator_context_budget"]["handoff_recommended"])
        self.assertIn("evidence_bytes", payload["coordinator_context_budget"]["exceeded_limits"])
        self.assertTrue(any("Coordinator context budget exceeded" in warning for warning in payload["warnings"]))

    def test_next_cli_full_json_preserves_legacy_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _code, start_result = e2e_dev_harness.start(
                SimpleNamespace(
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
            )

            stdout = io.StringIO()
            with patch.object(
                sys,
                "argv",
                [
                    "e2e_dev_harness.py",
                    "next",
                    str(repo),
                    "--state",
                    str(start_result["run_state"]),
                    "--full-json",
                ],
            ), patch("sys.stdout", stdout):
                exit_code = e2e_dev_harness.main()
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertIn("workflow_plan", payload)
        self.assertIn("todo_policy", payload)
        self.assertNotIn("full_result_path", payload)

    def test_dispatch_beat_cli_quiet_default_omits_prompt_and_keeps_full_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_dir = repo / "docs" / "agent-runs" / "run"
            schedule = run_dir / "agent-schedule.json"
            state_path = run_dir / "run-state.json"
            role_template = Path("docs/agent-runs/run/agent-roles/code-developer.md")
            handoff = Path("docs/agent-runs/run/handoffs/01-requirements-clarifier.md")
            output = Path("docs/agent-runs/run/service-plans/order-service/code-agent.md")
            install_hooks.install(repo, "claude")
            self.write_role_template(repo, role_template)
            self.write_ready_handoff(repo, handoff)
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

            stdout = io.StringIO()
            with patch.object(
                sys,
                "argv",
                [
                    "e2e_dev_harness.py",
                    "dispatch-beat",
                    str(repo),
                    "--schedule",
                    str(schedule),
                    "--state",
                    str(state_path),
                    "--runtime",
                    "claude-code",
                ],
            ), patch("sys.stdout", stdout):
                exit_code = e2e_dev_harness.main()
            payload = json.loads(stdout.getvalue())
            full_payload = json.loads((repo / payload["full_result_path"]).read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertIn("spawn_request_paths", payload)
        self.assertIn("task_prompt_paths", payload)
        self.assertNotIn("task_prompt", payload)
        self.assertNotIn("dispatch_packets", payload)
        self.assertIn("dispatch_packets", full_payload)
        self.assertIn("task_prompt", full_payload["dispatch_packets"][0])

    def test_prepare_reuses_single_knowledge_graph_detection(self) -> None:
        facts = {
            "poms": ["pom.xml"],
            "root_modules": [],
            "spring_entrypoints": [],
            "spring_configs": [],
            "design_docs_or_media_count": 0,
            "design_docs_or_media_sample": [],
            "graphify_graph": "graphify-out/graph.json",
            "graphify_graph_exists": False,
            "service_candidates": [],
            "multi_service": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "AGENT.md").write_text("# Root\n", encoding="utf-8")
            calls = []
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
                agent_orchestration_mode="auto",
                service_scope="discovery",
                agent_run_dir=None,
                run_date="2026-05-23",
                kg_mode="auto",
                dependency_scan_mode="off",
                write_dependency_report=False,
                dependency_output_dir=None,
                status_file=None,
            )

            def fake_detect(path: Path) -> dict:
                calls.append(path)
                return facts

            with patch.object(e2e_dev_harness.kg_refresh, "detect", side_effect=fake_detect):
                code, result = e2e_dev_harness.prepare(args)

        self.assertEqual(0, code)
        self.assertEqual(1, len(calls))
        self.assertEqual("discovery", result["orchestration"]["selected_mode"])
        self.assertEqual([], result["orchestration"]["agents"])

    def test_prepare_runs_gitnexus_first_dependency_scan(self) -> None:
        facts = {
            "poms": ["pom.xml"],
            "root_modules": [],
            "spring_entrypoints": [],
            "spring_configs": [],
            "design_docs_or_media_count": 0,
            "design_docs_or_media_sample": [],
            "graphify_graph": "graphify-out/graph.json",
            "graphify_graph_exists": False,
            "service_candidates": ["services/order-service", "services/payment-service"],
            "multi_service": True,
        }
        dependency_result = {
            "ready": True,
            "tool_priority": ["gitnexus", "deterministic-scan", "graphify"],
            "dependencies": [],
            "unresolved_questions": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "AGENT.md").write_text("# Root\n", encoding="utf-8")
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
                dependency_scan_mode="strict",
                write_dependency_report=False,
                dependency_output_dir=None,
                status_file=None,
            )

            with (
                patch.object(e2e_dev_harness.kg_refresh, "detect", return_value=facts),
                patch.object(e2e_dev_harness.cross_service_dependency_scan, "scan", return_value=dependency_result) as scan,
            ):
                code, result = e2e_dev_harness.prepare(args)

        self.assertEqual(0, code)
        scan.assert_called_once()
        self.assertEqual("strict", scan.call_args.kwargs["gitnexus_mode"])
        self.assertEqual(["gitnexus", "deterministic-scan", "graphify"], result["cross_service_dependencies"]["tool_priority"])

    def test_dependency_report_recommends_affected_services_for_plan(self) -> None:
        facts = {
            "service_candidates": ["services/order-service", "services/payment-service", "services/catalog-service"],
            "multi_service": True,
            "design_docs_or_media_count": 0,
            "spring_entrypoints": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            report = repo / "knowledge-graph" / "cross-service-dependencies.json"
            report.parent.mkdir(parents=True)
            report.write_text(
                json.dumps(
                    {
                        "ready": True,
                        "dependencies": [
                            {
                                "kind": "http",
                                "source_service": "services/order-service",
                                "target_service": "services/payment-service",
                            }
                        ],
                        "unresolved_questions": [],
                    }
                ),
                encoding="utf-8",
            )

            result = e2e_dev_harness.orchestration_status(
                repo,
                "auto",
                None,
                service_scope="auto",
                facts=facts,
                dependency_report=report,
            )

        self.assertEqual("affected", result["resolved_service_scope"])
        self.assertEqual(["services/order-service", "services/payment-service"], result["selected_services"])

    def test_cli_gate_accepts_rework_dir(self) -> None:
        design_text = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Return a quote.

            ## Scope
            - sample-service

            ## Use Cases
            - Create quote.

            ## Acceptance Criteria
            - Quote is returned.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote is returned | Create quote | services/sample-service | QuoteTest | QuoteService | reviewed | covered |
            """
        ).strip()
        rework = textwrap.dedent(
            """
            # Rework Item

            - Source: coverage-reviewer
            - Related AC: AC-1
            - Affected Services: services/sample-service
            - Problem Type: missing-code
            - Return Phase: tdd-implement
            - Required Red Test: QuoteServiceTest covers AC-1
            - Evidence: Completion review found the code path missing.
            - Exit Criteria: Completion gate passes after code refs are verified.
            - Status: open
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red.txt"
            matrix = repo / "docs" / "agent-runs" / "run" / "evidence" / "coverage.md"
            unit = repo / "docs" / "agent-runs" / "run" / "evidence" / "unit.txt"
            review = repo / "docs" / "agent-runs" / "run" / "evidence" / "business.md"
            rework_dir = repo / "docs" / "agent-runs" / "run" / "rework"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            rework_dir.mkdir(parents=True)
            design.write_text(design_text, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn -pl services/sample-service -am test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            (rework_dir / "rework-001.md").write_text(rework, encoding="utf-8")
            args = SimpleNamespace(
                repo=repo,
                design_doc=design,
                kg_status_file=kg,
                phase="completion",
                red_test_evidence=red,
                coverage_matrix=matrix,
                unit_test_evidence=unit,
                business_review=review,
                memory_updates=None,
                dependency_report=None,
                rework_dir=[rework_dir],
                skip_spring_static_check=True,
                status_file=None,
            )

            code, result = e2e_dev_harness.gate(args)

        self.assertEqual(2, code)
        self.assertEqual(1, result["rework"]["open_count"])

    def test_cli_gate_accepts_implementation_manifest(self) -> None:
        design_text = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Add a quote endpoint.

            ## Scope
            - services/sample-service

            ## Use Cases
            - Return a quote.

            ## Acceptance Criteria
            - AC-1 QuoteService returns a quote.

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Quote is returned | Create quote | services/sample-service | QuoteServiceTest | QuoteService | reviewed | covered |
            """
        ).strip()
        manifest = textwrap.dedent(
            """
            | id | module | artifact | artifact_type | source | required | tests | status | evidence |
            | --- | --- | --- | --- | --- | --- | --- | --- | --- |
            | IM-1 | services/sample-service | services/sample-service/src/main/java/com/example/QuoteService.java | service | AC-1 explicit-requirement | yes | QuoteServiceTest | verified | done |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            artifact = repo / "services/sample-service/src/main/java/com/example/QuoteService.java"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("class QuoteService {}\n", encoding="utf-8")
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red.txt"
            matrix = repo / "docs" / "agent-runs" / "run" / "evidence" / "coverage.md"
            unit = repo / "docs" / "agent-runs" / "run" / "evidence" / "unit.txt"
            review = repo / "docs" / "agent-runs" / "run" / "evidence" / "business.md"
            manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            approval = repo / "approval.md"
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            design.write_text(design_text, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            red.write_text("Red test failed for expected reason.\n", encoding="utf-8")
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn -pl services/sample-service -am test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            manifest_path.write_text(manifest, encoding="utf-8")
            approval.write_text("Approval: user-approved\n", encoding="utf-8")
            review_dir = self.write_semantic_reviews(repo)
            args = SimpleNamespace(
                repo=repo,
                design_doc=design,
                kg_status_file=kg,
                phase="completion",
                red_test_evidence=red,
                coverage_matrix=matrix,
                unit_test_evidence=unit,
                business_review=review,
                memory_updates=None,
                dependency_report=None,
                rework_dir=None,
                review_dir=[review_dir],
                require_semantic_reviews=False,
                implementation_manifest=manifest_path,
                skip_spring_static_check=True,
                no_harness_state=True,
                harness_state_approval=approval,
                status_file=None,
            )

            code, result = e2e_dev_harness.gate(args)

        self.assertEqual(0, code, result.get("blocked_reasons"))
        self.assertTrue(result["implementation_manifest"]["ready"])

    def test_cli_gate_accepts_dependency_report(self) -> None:
        design_text = textwrap.dedent(
            """
            # Feature

            ## Goal
            - Call payment service when an order is created.

            ## Scope
            - services/order-service
            - services/payment-service

            ## Use Cases
            - order-service calls payment-service over HTTP.

            ## Acceptance Criteria
            - AC-1 Payment callback is delivered.

            ## Change Logic
            - Current behavior: order creation does not call payment.
            - Target behavior: order creation invokes payment callback flow.
            - Runtime path: OrderController -> OrderService -> PaymentClient -> PaymentController.
            - State/data effect: sends payment request payload and stores callback status.

            ## Impact Summary
            - Source: GitNexus impact + dependency scanner
            - Raw Evidence: docs/agent-runs/run/evidence/impact-analysis.json

            | type | interface | affected callers/consumers | related AC | required tests/contracts | risk |
            | --- | --- | --- | --- | --- | --- |
            | HTTP | order-service -> payment-service callback | services/order-service, services/payment-service | AC-1 | PaymentCallbackTest; contract ACK | high |

            ## Test Design
            - Unit test first.

            ## Open Questions
            None
            """
        ).strip()
        coverage = textwrap.dedent(
            """
            | id | acceptance | use_case | service | tests | code_refs | business_review | status |
            | --- | --- | --- | --- | --- | --- | --- | --- |
            | AC-1 | Payment callback is delivered | HTTP flow | services/order-service, services/payment-service | PaymentCallbackTest | PaymentClient, PaymentController | reviewed | covered |
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            kg = repo / "knowledge-graph" / "knowledge-graph-refresh.json"
            red = repo / "docs" / "agent-runs" / "run" / "evidence" / "red.txt"
            matrix = repo / "docs" / "agent-runs" / "run" / "evidence" / "coverage.md"
            unit = repo / "docs" / "agent-runs" / "run" / "evidence" / "unit.txt"
            review = repo / "docs" / "agent-runs" / "run" / "evidence" / "business.md"
            manifest_path = repo / "docs" / "agent-runs" / "run" / "evidence" / "implementation-manifest.md"
            dependency_report = repo / "knowledge-graph" / "cross-service-dependencies.json"
            approval = repo / "approval.md"
            for path in (
                "services/order-service/src/main/java/com/example/PaymentClient.java",
                "services/payment-service/src/main/java/com/example/PaymentController.java",
            ):
                target = repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("class Placeholder {}\n", encoding="utf-8")
            design.parent.mkdir(parents=True)
            kg.parent.mkdir(parents=True)
            matrix.parent.mkdir(parents=True)
            dependency_report.parent.mkdir(parents=True, exist_ok=True)
            design.write_text(design_text, encoding="utf-8")
            kg.write_text('{"selected_tools":["gitnexus"]}\n', encoding="utf-8")
            write_command_evidence(red, "mvn test -Dtest=PaymentCallbackTest", exit_code=1)
            matrix.write_text(coverage, encoding="utf-8")
            write_command_evidence(unit, "mvn test")
            review.write_text("Reviewed business behavior against AC-1.\n", encoding="utf-8")
            manifest_path.write_text(
                textwrap.dedent(
                    """
                    | id | module | artifact | artifact_type | source | required | tests | status | evidence |
                    | --- | --- | --- | --- | --- | --- | --- | --- | --- |
                    | IM-1 | services/order-service | services/order-service/src/main/java/com/example/PaymentClient.java | client | AC-1 dependency-report | yes | PaymentCallbackTest | verified | done |
                    | IM-2 | services/payment-service | services/payment-service/src/main/java/com/example/PaymentController.java | controller | AC-1 dependency-report | yes | PaymentCallbackTest | verified | done |
                    """
                ).strip(),
                encoding="utf-8",
            )
            dependency_report.write_text(
                json.dumps(
                    {
                        "ready": True,
                        "tool_priority": ["gitnexus", "deterministic-scan"],
                        "gitnexus": {"primary": True, "available": True, "verified": True},
                        "dependencies": [{"kind": "http"}],
                        "unresolved_questions": [],
                    }
                ),
                encoding="utf-8",
            )
            approval.write_text("Approval: user-approved\n", encoding="utf-8")
            review_dir = self.write_semantic_reviews(repo)
            args = SimpleNamespace(
                repo=repo,
                design_doc=design,
                kg_status_file=kg,
                phase="completion",
                red_test_evidence=red,
                coverage_matrix=matrix,
                unit_test_evidence=unit,
                business_review=review,
                memory_updates=None,
                dependency_report=dependency_report,
                implementation_manifest=manifest_path,
                rework_dir=None,
                review_dir=[review_dir],
                require_semantic_reviews=False,
                skip_spring_static_check=True,
                no_harness_state=True,
                harness_state_approval=approval,
                status_file=None,
            )

            code, result = e2e_dev_harness.gate(args)

        self.assertEqual(0, code, result.get("blocked_reasons"))
        self.assertTrue(result["dependency_report"]["ready"])

    def test_verify_strict_workflow_blocks_skip_maven(self) -> None:
        args = SimpleNamespace(
            repo=Path("."),
            design_doc=None,
            path=None,
            service=None,
            agent_mode="off",
            agent_scope="auto",
            include_agent_content=False,
            max_agent_chars=12000,
            max_discovered_services=agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT,
            superpowers_mode="auto",
            memory_mode="off",
            agent_orchestration_mode="off",
            service_scope="discovery",
            agent_run_dir=None,
            run_date="2026-05-23",
            kg_mode="auto",
            dependency_scan_mode="auto",
            write_dependency_report=True,
            dependency_output_dir=None,
            run_gate=False,
            phase="planning",
            kg_status_file=None,
            red_test_evidence=None,
            coverage_matrix=None,
            unit_test_evidence=None,
            business_review=None,
            memory_updates=None,
            dependency_report=None,
            rework_dir=None,
            skip_spring_static_check=False,
            skip_maven=True,
            strict_workflow=True,
            workflow_approval=None,
            status_file=None,
        )
        prepare_result = {
            "blocked": False,
            "agent_instructions": {"blocked": False},
            "superpowers": {"blocked": False, "enabled": True},
            "memory": {"blocked": False},
            "orchestration": {"blocked": False},
            "knowledge_graph": {"selected_tools": ["gitnexus"]},
            "cross_service_dependencies": {
                "enabled": True,
                "mode": "auto",
                "ready": True,
                "report_paths": {"json": "knowledge-graph/cross-service-dependencies.json"},
            },
        }

        with patch.object(e2e_dev_harness, "prepare", return_value=(0, prepare_result)):
            code, result = e2e_dev_harness.verify(args)

        self.assertEqual(2, code)
        self.assertFalse(result["workflow_guard"]["ready"])
        self.assertTrue(any("Maven" in reason for reason in result["workflow_guard"]["blocked_reasons"]))

    def test_verify_reports_missing_maven_without_traceback(self) -> None:
        args = SimpleNamespace(
            repo=Path("."),
            design_doc=None,
            path=None,
            service=None,
            agent_mode="off",
            agent_scope="auto",
            include_agent_content=False,
            max_agent_chars=12000,
            max_discovered_services=agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT,
            superpowers_mode="auto",
            memory_mode="off",
            agent_orchestration_mode="off",
            service_scope="discovery",
            agent_run_dir=None,
            run_date="2026-05-23",
            kg_mode="auto",
            dependency_scan_mode="auto",
            write_dependency_report=True,
            dependency_output_dir=None,
            run_gate=False,
            phase="planning",
            kg_status_file=None,
            red_test_evidence=None,
            coverage_matrix=None,
            unit_test_evidence=None,
            business_review=None,
            memory_updates=None,
            dependency_report=None,
            implementation_manifest=None,
            rework_dir=None,
            skip_spring_static_check=False,
            skip_maven=False,
            strict_workflow=False,
            workflow_approval=None,
            status_file=None,
            module=None,
        )
        prepare_result = {"blocked": False}

        with (
            patch.object(e2e_dev_harness, "prepare", return_value=(0, prepare_result)),
            patch.object(e2e_dev_harness.shutil, "which", return_value=None),
            patch.object(e2e_dev_harness.subprocess, "run") as subprocess_run,
        ):
            code, result = e2e_dev_harness.verify(args)

        self.assertEqual(127, code)
        self.assertEqual(127, result["maven"]["exit_code"])
        self.assertIn("Maven executable not found", result["maven"]["stderr_tail"])
        subprocess_run.assert_not_called()

    def test_verify_reports_maven_timeout_without_hanging(self) -> None:
        args = SimpleNamespace(
            repo=Path("."),
            design_doc=None,
            path=None,
            service=None,
            agent_mode="off",
            agent_scope="auto",
            include_agent_content=False,
            max_agent_chars=12000,
            max_discovered_services=agent_instructions.DEFAULT_DISCOVERED_SERVICE_LIMIT,
            superpowers_mode="auto",
            memory_mode="off",
            agent_orchestration_mode="off",
            service_scope="discovery",
            agent_run_dir=None,
            run_date="2026-05-23",
            kg_mode="auto",
            dependency_scan_mode="auto",
            write_dependency_report=True,
            dependency_output_dir=None,
            run_gate=False,
            phase="planning",
            kg_status_file=None,
            red_test_evidence=None,
            coverage_matrix=None,
            unit_test_evidence=None,
            business_review=None,
            memory_updates=None,
            dependency_report=None,
            implementation_manifest=None,
            rework_dir=None,
            skip_spring_static_check=False,
            skip_maven=False,
            strict_workflow=False,
            workflow_approval=None,
            status_file=None,
            module=None,
        )

        with (
            patch.object(e2e_dev_harness, "prepare", return_value=(0, {"blocked": False})),
            patch.object(e2e_dev_harness.shutil, "which", return_value="mvn"),
            patch.object(
                e2e_dev_harness.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(["mvn", "test"], 600, output="partial"),
            ),
        ):
            code, result = e2e_dev_harness.verify(args)

        self.assertEqual(124, code)
        self.assertEqual(124, result["maven"]["exit_code"])
        self.assertIn("timed out", result["maven"]["stderr_tail"])




if __name__ == "__main__":
    unittest.main()
