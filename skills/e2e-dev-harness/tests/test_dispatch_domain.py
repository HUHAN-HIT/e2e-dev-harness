"""cli/commands/dispatch.run surfaces the run-state `domain` block (if any) as
an extra_context line; a backend run (no domain) is byte-identical to before."""
from types import SimpleNamespace

from e2e_harness.core import run_state
from e2e_harness.cli.commands import dispatch as dispatch_cmd


def test_dispatch_surfaces_domain_in_context(tmp_path):
    st = run_state.new_run_state("r", "f", "q",
        domain={"name": "frontend", "test_runner": "vitest", "review_profile": "frontend-default"})
    st["current_phase"] = "CLARIFIED"
    p = tmp_path / "run-state.json"
    run_state.save(p, st)
    args = SimpleNamespace(state=str(p), repo=str(tmp_path), runtime="codex")
    code, packet = dispatch_cmd.run(args)
    assert code == 0
    assert any("domain:frontend" in c and "test_runner:vitest" in c
               and "review_profile:frontend-default" in c for c in packet["context_paths"])


def test_dispatch_backend_no_domain_unchanged(tmp_path):
    st = run_state.new_run_state("r", "f", "q")  # no domain (backend default)
    st["current_phase"] = "CLARIFIED"
    p = tmp_path / "run-state.json"
    run_state.save(p, st)
    args = SimpleNamespace(state=str(p), repo=str(tmp_path), runtime="codex")
    code, packet = dispatch_cmd.run(args)
    assert code == 0
    assert packet["context_paths"] == [str(p)]   # only the run-state pointer


def test_dispatch_includes_language_profile_path_when_bound(tmp_path):
    profile = tmp_path / "docs" / "agent-runs" / "r" / "language-profile.json"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("{}", encoding="utf-8")
    st = run_state.new_run_state("r", "f", "q")
    st["current_phase"] = "CLARIFIED"
    st["language"] = {
        "schema": "e2e-harness.language-binding.v1",
        "profile_path": str(profile.relative_to(tmp_path)),
        "primary_language": "typescript",
        "profiles": ["typescript"],
        "source": "detected",
    }
    p = profile.parent / "run-state.json"
    run_state.save(p, st)
    args = SimpleNamespace(state=str(p), repo=str(tmp_path), runtime="codex")

    code, packet = dispatch_cmd.run(args)

    assert code == 0
    assert str(profile.relative_to(tmp_path)) in packet["context_paths"]
