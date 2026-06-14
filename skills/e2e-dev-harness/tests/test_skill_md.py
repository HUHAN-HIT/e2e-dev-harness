from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


def test_skill_md_has_frontmatter_and_verbs():
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "name: e2e-dev-harness" in text
    for verb in ("start", "next", "dispatch", "submit", "gate", "status"):
        assert verb in text
    assert "指针" in text or "pointer" in text
    assert "VERIFIED" in text


def test_skill_md_uses_resume_safe_cli_commands():
    text = SKILL.read_text(encoding="utf-8")
    command_block = text.split("## 循环", 1)[0]

    assert "e2e-harness start" in command_block
    assert "e2e-harness status --state <run-state>" in command_block
    assert "S=skills/e2e-dev-harness/scripts/e2e_dev_harness.py" not in command_block
    assert "Do not use repo-relative" in command_block


def test_skill_md_documents_tiers_and_review_fanout():
    text = SKILL.read_text(encoding="utf-8")
    for tier in ("minimal", "standard", "critical", "audited"):
        assert tier in text
    assert "r1" in text and "r2" in text and "r3" in text  # review fan-out
    assert "--tier" in text


def test_skill_md_documents_adversarial_optin_pipeline():
    """Rollout step 5: the tier table must surface the opt-in adversarial pipeline
    and the --pipeline selection path (it is not a --tier auto choice)."""
    text = SKILL.read_text(encoding="utf-8")
    assert "adversarial" in text
    assert "--pipeline adversarial" in text


def test_skill_md_documents_adversarial_recommendation():
    """Slice 3: the tier-recommendation contract documents the advisory
    adversarial_review suggestion (kept explicit / user-confirmed)."""
    text = SKILL.read_text(encoding="utf-8")
    assert "adversarial_review" in text
    assert "suggested" in text


def test_skill_md_documents_auto_as_default_tier():
    text = SKILL.read_text(encoding="utf-8")
    assert "default `auto`" in text
    assert "default `minimal`" not in text


def test_skill_md_documents_tier_options_and_gitnexus_evidence():
    text = SKILL.read_text(encoding="utf-8")

    assert "tier_recommendation" in text
    assert "options" in text
    assert "recommended_tier" in text
    assert "selected_tier" in text
    assert "GitNexus impact" in text
    assert "downgrade" in text
    assert "requested_below_recommended" in text
    assert "requires_provenance=true" in text
    assert "blocked=false" in text


def test_skill_md_documents_tier_preview_confirmation():
    text = SKILL.read_text(encoding="utf-8")
    command_block = text.split("## 循环", 1)[0]

    assert "--preview-tier" in text
    assert "tier-preview.v1" in text
    assert "does not create" in text
    assert "run-state.json" in text
    assert "Codex" in text
    assert "start --tier <choice>" in text
    assert "Do not implement this as a stdin prompt" in text
    assert "non-interactive" in text

    preview_cmd = "e2e-harness start --preview-tier"
    confirmed_cmd = 'e2e-harness start --repo . --feature "<feat>" --request-file /tmp/req.txt --tier <choice>'
    assert preview_cmd in command_block
    assert confirmed_cmd in command_block
    assert command_block.index(preview_cmd) < command_block.index(confirmed_cmd)


def test_skill_md_documents_beat_cycle_for_module_band():
    text = SKILL.read_text(encoding="utf-8")
    assert "tracks_frontier" in text
    assert "beat" in text or "一拍" in text
    # the concurrent fan-out + reconcile loop must be described
    assert "module_band" in text
    assert "await" in text or "并发" in text


def test_skill_md_documents_language_profiles_and_js_ts_substance():
    text = SKILL.read_text(encoding="utf-8")

    assert "--language-profile" in text
    assert "language-profile.json" in text
    assert "javascript" in text and "typescript" in text
    assert "analyzer_warnings" in text
    assert "test_substance" in text


def test_skill_md_documents_rapid_optin_pipeline():
    text = SKILL.read_text(encoding="utf-8")

    assert "`rapid`" in text
    assert "start --pipeline rapid" in text
    assert "CREATED→CLARIFIED→IMPLEMENTED→VERIFIED" in text
