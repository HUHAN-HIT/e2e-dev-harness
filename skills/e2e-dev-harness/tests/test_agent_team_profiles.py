from pathlib import Path

import pytest

from e2e_harness.adapters.agent_team import registry, schema


def test_bundled_profiles_load_in_deterministic_order():
    profiles = registry.load_bundled_profiles()

    assert [profile["name"] for profile in profiles] == [
        "default-adversarial",
        "default-audited",
        "default-critical",
        "default-minimal",
        "default-rapid",
        "default-standard",
    ]
    assert all(profile["schema"] == schema.PROFILE_SCHEMA for profile in profiles)


def test_project_local_profile_requires_explicit_name(tmp_path):
    local_dir = tmp_path / ".e2e" / "agent-teams"
    local_dir.mkdir(parents=True)
    (local_dir / "custom.yaml").write_text(
        "\n".join(
            [
                "schema: e2e-dev-harness.agent-team-profile.v1",
                "name: custom",
                "roles:",
                "  requirements-clarifier:",
                "    skill: e2e-harness-clarification",
                "    runtime_subagent_type: requirements-clarifier",
                "    max_workers: 1",
            ]
        ),
        encoding="utf-8",
    )

    names = [profile["name"] for profile in registry.load_profiles(tmp_path)]
    assert "custom" not in names
    assert registry.load_profile("custom", repo_root=tmp_path)["name"] == "custom"


def test_invalid_profile_error_identifies_path_and_field(tmp_path):
    profile = tmp_path / "bad.yaml"
    profile.write_text(
        "\n".join(
            [
                "schema: e2e-dev-harness.agent-team-profile.v1",
                "name: broken",
                "roles:",
                "  semantic-reviewer:",
                "    runtime_subagent_type: semantic-reviewer",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(schema.ProfileValidationError) as exc:
        schema.load_profile_file(profile)

    message = str(exc.value)
    assert str(profile) in message
    assert "roles.semantic-reviewer.skill" in message
