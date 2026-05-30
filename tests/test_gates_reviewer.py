"""Reviewer gate: code-review readiness and evidence."""
from __future__ import annotations

import sys
import hashlib
import json
import tempfile
import textwrap
import unittest

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "e2e-dev-harness" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import reviewer_gate  # noqa: E402


class ReviewerGateTests(unittest.TestCase):
    PROFILE_CHECKLIST = {
        "design": ["ac-completeness", "dependency-impact", "security-sensitive-paths"],
        "test": ["happy-and-failure-paths", "contract-coverage", "security-negative-paths"],
        "implementation": [
            "ac-code-path-trace",
            "implementation-completeness",
            "security-negative-paths",
            "project-pattern-consistency",
        ],
    }

    def profile_checklist(self, phase: str) -> str:
        items = self.PROFILE_CHECKLIST.get(phase, [])
        if not items:
            return ""
        return "## Required Review Checklist\n\n" + "\n".join(f"- [x] {item}: checked." for item in items)

    def review_doc(
        self,
        phase: str,
        status: str = "approved",
        findings: str = "None",
        required_rework: str = "None",
        checklist: str = "",
        request: str | None = None,
        developer_agent: str = "developer-agent-1",
        reviewer_agent: str = "reviewer-agent-1",
        independence: str = "independent-agent",
        request_hash: str = "",
        reviewer_session: str = "review-session-1",
        reviewer_invocation: str | None = None,
    ) -> str:
        request = request or f"docs/agent-runs/run/review-requests/{phase}-review-request.md"
        reviewer_invocation = reviewer_invocation or f"docs/agent-runs/run/review-invocations/{phase}-reviewer-invocation.json"
        request_hash_line = f"- Request Hash: {request_hash}\n" if request_hash else ""
        return textwrap.dedent(
            f"""
            # {phase.title()} Review

            - Phase: {phase}
            - Reviewer: semantic-reviewer
            - Review Request: {request}
            - Developer Agent: {developer_agent}
            - Reviewer Agent: {reviewer_agent}
            - Reviewer Session: {reviewer_session}
            - Reviewer Invocation: {reviewer_invocation}
            {request_hash_line.rstrip()}
            - Independence: {independence}
            - Context Boundary: request-scoped; no inherited developer chat context
            - No Code Changes: confirmed
            - Scope: services/payment-service
            - Inputs Reviewed: design doc; tests; implementation files
            - Findings: {findings}
            - Required Rework: {required_rework}
            - Status: {status}

            {checklist}
            """
        ).strip()

    def write_request(
        self,
        repo: Path,
        phase: str,
        request_name: str | None = None,
        output_name: str | None = None,
        request_phase: str | None = None,
        developer_agent: str = "developer-agent-1",
        reviewer_agent: str = "reviewer-agent-1",
        reviewer_session: str = "review-session-1",
    ) -> str:
        request_name = request_name or f"{phase}-review-request.md"
        output_name = output_name or {
            "design": "R1-design-review.md",
            "test": "R2-test-review.md",
            "implementation": "R3-implementation-review.md",
        }.get(phase, f"{phase}-review.md")
        request = repo / "docs" / "agent-runs" / "run" / "review-requests" / request_name
        invocation = repo / "docs" / "agent-runs" / "run" / "review-invocations" / f"{phase}-reviewer-invocation.json"
        invocation.parent.mkdir(parents=True, exist_ok=True)
        request.parent.mkdir(parents=True, exist_ok=True)
        request.write_text(
            textwrap.dedent(
                f"""
                # {phase.title()} Review Request

                - Phase: {request_phase or phase}
                - Reviewer Role: independent semantic reviewer
                - Context Package: request-scoped; no inherited developer chat context
                - Allowed Inputs: design, tests, implementation refs, dependency report
                - Forbidden: inherited developer chat context; production-code edits; self-review
                - Output: docs/agent-runs/run/reviews/{output_name}
                - Developer Agent: {developer_agent}
                - Reviewer Agent: {reviewer_agent}
                - Reviewer Invocation: docs/agent-runs/run/review-invocations/{phase}-reviewer-invocation.json
                """
            ).strip(),
            encoding="utf-8",
        )
        invocation.write_text(
            json.dumps(
                {
                    "runtime": "claude-code",
                    "invocation_type": "subagent",
                    "developer_agent": developer_agent,
                    "developer_session": "developer-session-1",
                    "reviewer_agent": reviewer_agent,
                    "reviewer_session": reviewer_session,
                    "context_pack": f"docs/agent-runs/run/review-requests/{request_name}",
                    "review_request": f"docs/agent-runs/run/review-requests/{request_name}",
                    "output": f"docs/agent-runs/run/reviews/{output_name}",
                    "fork_context": False,
                    "context_policy": "request-scoped; no-inherited-developer-chat-context",
                    "status": "completed",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return str(request.relative_to(repo)).replace("\\", "/")

    def request_hash(self, repo: Path, request: str) -> str:
        return hashlib.sha256((repo / request).read_bytes()).hexdigest()

    def write_service_review(
        self,
        repo: Path,
        service: str,
        phase: str,
        developer_agent: str = "developer-agent-1",
    ) -> Path:
        review_name = {
            "test": "R2-test-review.md",
            "implementation": "R3-implementation-review.md",
        }[phase]
        request_name = {
            "test": "R2-test-review-request.md",
            "implementation": "R3-implementation-review-request.md",
        }[phase]
        reviewer_agent = f"reviewer-agent-{service}-{phase}"
        reviewer_session = f"review-session-{service}-{phase}"
        service_base = repo / "docs" / "agent-runs" / "run" / "service-plans" / service
        request = service_base / "review-requests" / request_name
        review = service_base / "reviews" / review_name
        invocation = service_base / "review-invocations" / f"{phase}-reviewer-invocation.json"
        request.parent.mkdir(parents=True, exist_ok=True)
        review.parent.mkdir(parents=True, exist_ok=True)
        invocation.parent.mkdir(parents=True, exist_ok=True)
        request_rel = str(request.relative_to(repo)).replace("\\", "/")
        review_rel = str(review.relative_to(repo)).replace("\\", "/")
        invocation_rel = str(invocation.relative_to(repo)).replace("\\", "/")
        request.write_text(
            textwrap.dedent(
                f"""
                # {service} {phase.title()} Review Request

                - Phase: {phase}
                - Reviewer Role: independent semantic reviewer
                - Context Package: request-scoped; no inherited developer chat context
                - Allowed Inputs: design, tests, implementation refs, dependency report, service plan
                - Forbidden: inherited developer chat context; production-code edits; self-review
                - Output: {review_rel}
                - Developer Agent: {developer_agent}
                - Reviewer Agent: {reviewer_agent}
                - Reviewer Invocation: {invocation_rel}
                """
            ).strip(),
            encoding="utf-8",
        )
        invocation.write_text(
            json.dumps(
                {
                    "runtime": "claude-code",
                    "invocation_type": "subagent",
                    "developer_agent": developer_agent,
                    "developer_session": f"developer-session-{service}",
                    "reviewer_agent": reviewer_agent,
                    "reviewer_session": reviewer_session,
                    "context_pack": request_rel,
                    "review_request": request_rel,
                    "output": review_rel,
                    "fork_context": False,
                    "context_policy": "request-scoped; no-inherited-developer-chat-context",
                    "status": "completed",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        review.write_text(
            self.review_doc(
                phase,
                checklist=self.profile_checklist(phase),
                request=request_rel,
                request_hash=hashlib.sha256(request.read_bytes()).hexdigest(),
                developer_agent=developer_agent,
                reviewer_agent=reviewer_agent,
                reviewer_session=reviewer_session,
                reviewer_invocation=invocation_rel,
            ).replace("- Scope: services/payment-service", f"- Scope: {service}"),
            encoding="utf-8",
        )
        return review

    def test_reviewer_gate_requires_all_phase_reviews_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "design")
            (review_dir / "R1-design-review.md").write_text(
                self.review_doc("design", request=request, request_hash=self.request_hash(repo, request)),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["design", "test", "implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("test" in reason.lower() for reason in result["blocked_reasons"]))
        self.assertTrue(any("implementation" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_allows_approved_phase_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            for name, phase in (
                ("R1-design-review.md", "design"),
                ("R2-test-review.md", "test"),
                ("R3-implementation-review.md", "implementation"),
            ):
                request = self.write_request(repo, phase)
                (review_dir / name).write_text(
                    self.review_doc(phase, request=request, request_hash=self.request_hash(repo, request)),
                    encoding="utf-8",
                )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["design", "test", "implementation"])

        self.assertTrue(result["ready"])
        self.assertEqual(["design", "implementation", "test"], sorted(result["covered_phases"]))

    def test_reviewer_gate_blocks_open_review_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    status="blocked",
                    findings="Missing VnpayQrOrderRS.",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("blocked" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_findings_without_rework_or_blocking_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    findings="Missing negative authorization test.",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("findings" in reason.lower() and "rework" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_uses_profile_required_checklist_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            profile = repo / "review-profiles" / "strict.json"
            profile.parent.mkdir(parents=True)
            profile.write_text(
                json.dumps(
                    {
                        "required_checklist": {
                            "implementation": [
                                {
                                    "id": "security-negative-paths",
                                    "title": "Security negative paths",
                                    "required": True,
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    checklist="## Review Checklist\n\n- [x] project-pattern-consistency: checked",
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(
                repo,
                [review_dir],
                require_phases=["implementation"],
                review_profile=profile,
            )

        self.assertFalse(result["ready"])
        self.assertTrue(any("security-negative-paths" in reason for reason in result["blocked_reasons"]))

    def test_reviewer_gate_resolves_bundled_default_review_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    checklist=textwrap.dedent(
                        """
                        ## Review Checklist

                        - [x] ac-code-path-trace: checked
                        - [x] implementation-completeness: checked
                        - [x] security-negative-paths: checked
                        - [x] project-pattern-consistency: checked
                        """
                    ).strip(),
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(
                repo,
                [review_dir],
                require_phases=["implementation"],
                review_profile=Path("skills/e2e-dev-harness/review-profiles/default.json"),
        )

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertTrue(result["review_profile"].replace("\\", "/").endswith("skills/e2e-dev-harness/review-profiles/default.json"))

    def test_reviewer_gate_auto_discovers_project_review_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            profile = repo / ".e2e" / "review-profile.json"
            profile.parent.mkdir(parents=True)
            profile.write_text(
                json.dumps(
                    {
                        "required_checklist": {
                            "implementation": [
                                {
                                    "id": "project-specific-risk",
                                    "title": "Project-specific risk",
                                    "description": "Reviewer must check the project-specific edge case.",
                                    "severity": "blocker",
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    checklist="## Review Checklist\n\n- [x] project-pattern-consistency: checked",
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertEqual("project", result["review_profile_source"])
        self.assertTrue(result["review_profile"].replace("\\", "/").endswith(".e2e/review-profile.json"))
        self.assertTrue(any("project-specific-risk" in reason for reason in result["blocked_reasons"]))

    def test_reviewer_gate_explicit_profile_overrides_project_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            project_profile = repo / ".e2e" / "review-profile.json"
            project_profile.parent.mkdir(parents=True)
            project_profile.write_text(
                '{"required_checklist":{"implementation":["project-specific-risk"]}}\n',
                encoding="utf-8",
            )
            explicit_profile = repo / "docs" / "review-profiles" / "explicit.json"
            explicit_profile.parent.mkdir(parents=True)
            explicit_profile.write_text(
                '{"required_checklist":{"implementation":["project-pattern-consistency"]}}\n',
                encoding="utf-8",
            )
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    checklist="## Review Checklist\n\n- [x] project-pattern-consistency: checked",
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(
                repo,
                [review_dir],
                require_phases=["implementation"],
                review_profile=explicit_profile,
            )

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("explicit", result["review_profile_source"])
        self.assertTrue(result["review_profile"].replace("\\", "/").endswith("docs/review-profiles/explicit.json"))

    def test_reviewer_gate_merges_profile_extends_and_warns_for_warning_severity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            profile = repo / ".e2e" / "review-profile.json"
            profile.parent.mkdir(parents=True)
            profile.write_text(
                json.dumps(
                    {
                        "extends": "default",
                        "required_checklist": {
                            "implementation": [
                                {
                                    "id": "project-specific-risk",
                                    "title": "Project-specific risk",
                                    "severity": "blocker",
                                },
                                {
                                    "id": "observability-note",
                                    "title": "Observability note",
                                    "description": "Reviewer should mention logs or metrics when relevant.",
                                    "severity": "warning",
                                },
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    checklist=textwrap.dedent(
                        """
                        ## Review Checklist

                        - [x] ac-code-path-trace: checked
                        - [x] implementation-completeness: checked
                        - [x] security-negative-paths: checked
                        - [x] project-pattern-consistency: checked
                        - [x] project-specific-risk: checked
                        """
                    ).strip(),
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual("project", result["review_profile_source"])
        self.assertTrue(any("default.json" in path.replace("\\", "/") for path in result["review_profile_chain"]))
        self.assertTrue(any("observability-note" in warning for warning in result["warnings"]))

    def test_reviewer_gate_blocks_self_review_even_if_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    developer_agent="agent-1",
                    reviewer_agent="agent-1",
                    independence="self-review",
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("independent" in reason.lower() or "same" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_requires_existing_review_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            (review_dir / "R2-test-review.md").write_text(
                self.review_doc("test", request="docs/agent-runs/run/review-requests/missing.md", request_hash="0" * 64),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["test"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("review request" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_request_phase_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation", request_phase="test")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc("implementation", request=request, request_hash=self.request_hash(repo, request)),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("phase" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_request_output_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation", output_name="other-review.md")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc("implementation", request=request, request_hash=self.request_hash(repo, request)),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("declared" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_placeholder_agent_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(
                repo,
                "implementation",
                developer_agent="<developer-agent-id>",
                reviewer_agent="<independent-reviewer-agent-id>",
            )
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    developer_agent="<developer-agent-id>",
                    reviewer_agent="<independent-reviewer-agent-id>",
                    reviewer_session="<reviewer-session-id>",
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("placeholder" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_request_developer_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation", developer_agent="developer-agent-1")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    developer_agent="developer-agent-2",
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("developer agent" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_request_reviewer_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation", reviewer_agent="reviewer-agent-1")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    reviewer_agent="reviewer-agent-2",
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("reviewer agent" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_tampered_request_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc("implementation", request=request, request_hash="0" * 64),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("request hash" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_invocation_forked_from_developer_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            invocation = repo / "docs" / "agent-runs" / "run" / "review-invocations" / "implementation-reviewer-invocation.json"
            data = json.loads(invocation.read_text(encoding="utf-8"))
            data["fork_context"] = True
            invocation.write_text(json.dumps(data), encoding="utf-8")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc("implementation", request=request, request_hash=self.request_hash(repo, request)),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("fork_context" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_invocation_missing_runtime_isolation_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            invocation = repo / "docs" / "agent-runs" / "run" / "review-invocations" / "implementation-reviewer-invocation.json"
            data = json.loads(invocation.read_text(encoding="utf-8"))
            data.pop("runtime")
            data.pop("developer_session")
            invocation.write_text(json.dumps(data), encoding="utf-8")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc("implementation", request=request, request_hash=self.request_hash(repo, request)),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("runtime isolation fields" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_same_developer_and_reviewer_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation", reviewer_session="shared-session-1")
            invocation = repo / "docs" / "agent-runs" / "run" / "review-invocations" / "implementation-reviewer-invocation.json"
            data = json.loads(invocation.read_text(encoding="utf-8"))
            data["developer_session"] = "shared-session-1"
            data["reviewer_session"] = "shared-session-1"
            invocation.write_text(json.dumps(data), encoding="utf-8")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    reviewer_session="shared-session-1",
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("same developer session and reviewer session" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_independence_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc(
                    "implementation",
                    request=request,
                    request_hash=self.request_hash(repo, request),
                    independence="subagent",
                ),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("independence" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_blocks_missing_service_local_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            for service in ("jeepay-core", "jeepay-service"):
                (repo / "docs" / "agent-runs" / "run" / "service-plans" / service).mkdir(parents=True)
            for name, phase in (
                ("R1-design-review.md", "design"),
                ("R2-test-review.md", "test"),
                ("R3-implementation-review.md", "implementation"),
            ):
                request = self.write_request(repo, phase)
                (review_dir / name).write_text(
                    self.review_doc(phase, request=request, request_hash=self.request_hash(repo, request)),
                    encoding="utf-8",
                )

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["design", "test", "implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("jeepay-core" in reason and "test" in reason for reason in result["blocked_reasons"]))
        self.assertTrue(any("jeepay-service" in reason and "implementation" in reason for reason in result["blocked_reasons"]))

    def test_reviewer_gate_merges_explicit_review_dir_with_service_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            for name, phase in (
                ("R1-design-review.md", "design"),
                ("R2-test-review.md", "test"),
                ("R3-implementation-review.md", "implementation"),
            ):
                request = self.write_request(repo, phase)
                (review_dir / name).write_text(
                    self.review_doc(phase, request=request, request_hash=self.request_hash(repo, request)),
                    encoding="utf-8",
                )
            self.write_service_review(repo, "jeepay-core", "test")
            self.write_service_review(repo, "jeepay-core", "implementation")

            result = reviewer_gate.validate(repo, [review_dir], require_phases=["design", "test", "implementation"])

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertIn("jeepay-core", result["expected_services"])
        self.assertEqual(["implementation", "test"], sorted(result["covered_service_reviews"]["jeepay-core"]))

    def test_reviewer_gate_requires_r3_code_path_trace_for_each_acceptance_criterion(self) -> None:
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
                    - AC-2 Invalid input is rejected.

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None
                    """
                ).strip(),
                encoding="utf-8",
            )
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc("implementation", request=request, request_hash=self.request_hash(repo, request)),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], [design], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("code path trace" in reason.lower() and "AC-1" in reason for reason in result["blocked_reasons"]))

    def test_reviewer_gate_allows_r3_code_path_trace_for_each_acceptance_criterion(self) -> None:
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
                    - AC-2 Invalid input is rejected.

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None
                    """
                ).strip(),
                encoding="utf-8",
            )
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            trace = textwrap.dedent(
                """
                ## Code Path Trace

                - AC-1: QuoteController -> QuoteService.create -> QuoteRepository.save -> QuoteResponse.
                - AC-2: QuoteController -> QuoteRequestValidator.rejects invalid input -> error response.
                """
            ).strip()
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc("implementation", request=request, request_hash=self.request_hash(repo, request), checklist=trace),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], [design], require_phases=["implementation"])

        self.assertTrue(result["ready"], result["blocked_reasons"])

    def test_reviewer_gate_blocks_messaging_ac_without_sender_path_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Goal
                    - Publish refund callback.

                    ## Scope
                    - services/payment-service

                    ## Use Cases
                    - Refund succeeds.

                    ## Acceptance Criteria
                    - AC-1 Publish DMQ refund callback with topic, tag, group, and payload fields.

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None
                    """
                ).strip(),
                encoding="utf-8",
            )
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            trace = textwrap.dedent(
                """
                ## Code Path Trace

                - AC-1: RefundController -> RefundService.complete -> success response.
                """
            ).strip()
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc("implementation", request=request, request_hash=self.request_hash(repo, request), checklist=trace),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], [design], require_phases=["implementation"])

        self.assertFalse(result["ready"])
        self.assertTrue(any("messaging path trace" in reason.lower() for reason in result["blocked_reasons"]))

    def test_reviewer_gate_allows_messaging_ac_with_sender_path_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            design = repo / "docs" / "design" / "feature.md"
            design.parent.mkdir(parents=True)
            design.write_text(
                textwrap.dedent(
                    """
                    # Feature

                    ## Goal
                    - Publish refund callback.

                    ## Scope
                    - services/payment-service

                    ## Use Cases
                    - Refund succeeds.

                    ## Acceptance Criteria
                    - AC-1 Publish DMQ refund callback with topic, tag, group, and payload fields.

                    ## Test Design
                    - Unit test first.

                    ## Open Questions
                    None
                    """
                ).strip(),
                encoding="utf-8",
            )
            review_dir = repo / "docs" / "agent-runs" / "run" / "reviews"
            review_dir.mkdir(parents=True)
            request = self.write_request(repo, "implementation")
            trace = textwrap.dedent(
                """
                ## Code Path Trace

                - AC-1: RefundController -> RefundService.complete -> RefundCallbackDmqSender.send(topic, tag, group, payload) -> PaymentCallbackDmqSenderTest verifies payload fields.

                ## Messaging Path Trace

                - AC-1 sender/producer injection point: RefundService constructor injects RefundCallbackDmqSender.
                - AC-1 actual send call: RefundCallbackDmqSender.send(topic, tag, group, payload).
                - AC-1 topic/tag/group: refund.callback / success / payment-service.
                - AC-1 payload fields: refundId, status, amount, updatedAt.
                - AC-1 test evidence: PaymentCallbackDmqSenderTest verifies topic, tag, group, and payload.
                """
            ).strip()
            (review_dir / "R3-implementation-review.md").write_text(
                self.review_doc("implementation", request=request, request_hash=self.request_hash(repo, request), checklist=trace),
                encoding="utf-8",
            )

            result = reviewer_gate.validate(repo, [review_dir], [design], require_phases=["implementation"])

        self.assertTrue(result["ready"], result["blocked_reasons"])
        self.assertEqual([], result["items"][0]["missing_code_path_trace_acs"])




if __name__ == "__main__":
    unittest.main()
