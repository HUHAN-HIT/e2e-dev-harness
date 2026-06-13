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


def test_skill_md_documents_tiers_and_review_fanout():
    text = SKILL.read_text(encoding="utf-8")
    for tier in ("minimal", "standard", "critical", "audited"):
        assert tier in text
    assert "r1" in text and "r2" in text and "r3" in text  # review fan-out
    assert "--tier" in text


def test_skill_md_documents_auto_as_default_tier():
    text = SKILL.read_text(encoding="utf-8")
    assert "default `auto`" in text
    assert "default `minimal`" not in text


def test_skill_md_documents_tier_options_and_gitnexus_evidence():
    text = SKILL.read_text(encoding="utf-8")

    assert "tier_recommendation" in text
    assert "recommended_tier" in text
    assert "selected_tier" in text
    assert "GitNexus impact" in text
    assert "requires_provenance" in text


def test_skill_md_documents_beat_cycle_for_module_band():
    text = SKILL.read_text(encoding="utf-8")
    assert "tracks_frontier" in text
    assert "beat" in text or "一拍" in text
    # the concurrent fan-out + reconcile loop must be described
    assert "module_band" in text
    assert "await" in text or "并发" in text
