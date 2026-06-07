from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


def test_skill_md_has_frontmatter_and_verbs():
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "name: e2e-dev-harness-v2" in text
    for verb in ("start", "next", "dispatch", "submit", "gate", "status"):
        assert verb in text
    assert "指针" in text or "pointer" in text
    assert "VERIFIED" in text
