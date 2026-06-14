import json
from types import SimpleNamespace

from e2e_harness.adapters.language import profile as lp
from e2e_harness.cli.commands import start as start_cmd


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_detects_typescript_profile_with_capabilities(tmp_path):
    _write(tmp_path / "package.json", '{"devDependencies":{"vitest":"latest"}}')
    _write(tmp_path / "tsconfig.json", "{}")
    _write(tmp_path / "src" / "App.test.tsx", "test('x', () => {})")

    prof = lp.resolve_language_profile(tmp_path, domain_hint="frontend")

    assert prof["schema"] == lp.SCHEMA
    assert prof["primary_language"] == "typescript"
    assert prof["profiles"][0]["language"] == "typescript"
    assert prof["profiles"][0]["capabilities"]["test_substance"] is True
    assert prof["profiles"][0]["capabilities"]["scope_scan"] == "component"


def test_backend_marker_beats_small_touched_typescript_helper(tmp_path):
    _write(tmp_path / "pom.xml", "<project/>")
    _write(tmp_path / "src" / "main" / "java" / "App.java", "class App {}")
    _write(tmp_path / "tools" / "helper.test.ts", "test('x', () => {})")
    _write(tmp_path / "tools" / "helper.ts", "export const x = 1")

    prof = lp.resolve_language_profile(
        tmp_path,
        domain_hint="backend",
        touched_files=["tools/helper.test.ts", "tools/helper.ts"],
    )

    assert prof["primary_language"] == "java"
    assert [p["language"] for p in prof["profiles"]] == ["java", "typescript"]


def test_start_persists_language_profile_and_run_state_binding(tmp_path, monkeypatch):
    monkeypatch.setenv("E2E_HARNESS_DISABLE_EVENTS", "1")
    _write(tmp_path / "package.json", '{"devDependencies":{"vitest":"latest"}}')
    _write(tmp_path / "tsconfig.json", "{}")
    _write(tmp_path / "src" / "App.test.tsx", "test('x', () => expect(1).toBe(1))")
    args = SimpleNamespace(
        repo=str(tmp_path), feature="demo", feature_file=None, request="do x",
        request_file=None, tier="auto", pipeline=None, adapter=None, scan=False,
        preview_tier=False, language_profile=None,
    )

    code, result = start_cmd.run(args)

    assert code == 0
    state = json.loads((tmp_path / result["run_state"]).read_text(encoding="utf-8")) \
        if not str(result["run_state"]).startswith(str(tmp_path)) \
        else json.loads(open(result["run_state"], encoding="utf-8").read())
    binding = state["language"]
    assert binding["schema"] == lp.BINDING_SCHEMA
    assert binding["primary_language"] == "typescript"
    profile_path = tmp_path / binding["profile_path"]
    assert profile_path.is_file()
    persisted = json.loads(profile_path.read_text(encoding="utf-8"))
    assert persisted["primary_language"] == "typescript"


def test_explicit_language_profile_path_is_used(tmp_path):
    custom = tmp_path / ".e2e" / "language-profile.json"
    _write(custom, json.dumps({
        "schema": lp.SCHEMA,
        "profiles": [{
            "language": "python",
            "roots": ["service"],
            "test_runners": ["pytest"],
            "package_managers": [],
            "capabilities": {
                "command_replay": True,
                "test_substance": True,
                "scope_scan": "module",
                "dependency_graph": False,
                "browser_evidence": "none",
            },
        }],
        "primary_language": "python",
        "warnings": [],
    }))

    prof = lp.resolve_language_profile(tmp_path, explicit=str(custom))

    assert prof["source"] == "explicit-path"
    assert prof["primary_language"] == "python"
