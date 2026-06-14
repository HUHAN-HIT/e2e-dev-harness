"""Resolve immutable per-run language profiles."""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "e2e-harness.language-profile.v1"
BINDING_SCHEMA = "e2e-harness.language-binding.v1"

_ALIASES = {"js": "javascript", "ts": "typescript", "py": "python"}
_SUPPORTED = {"java", "javascript", "typescript", "python"}
_STRONG_MARKERS = {
    "java": ("pom.xml", "build.gradle", "build.gradle.kts"),
    "python": ("pyproject.toml", "setup.py"),
    "typescript": ("tsconfig.json",),
    "javascript": (),
}
_PACKAGE_MARKERS = {
    "python": ("pytest.ini",),
    "typescript": ("package.json", "vite.config.ts", "vitest.config.ts", "jest.config.ts"),
    "javascript": ("vite.config.js", "vitest.config.js", "jest.config.js"),
}
_EXTENSIONS = {
    "java": (".java",),
    "python": (".py",),
    "typescript": (".ts", ".tsx"),
    "javascript": (".js", ".jsx"),
}
_TEST_HINTS = (".test.", ".spec.", "_test.")


def resolve_language_profile(repo: str | Path, *, domain_hint: str | None = None,
                             explicit: str | None = None,
                             touched_files: list[str] | None = None) -> dict:
    repo = Path(repo).resolve()
    if explicit:
        loaded = _load_explicit(repo, explicit)
        if loaded is not None:
            return loaded
        lang = _normalize_language(explicit)
        return _profile_doc([_profile(lang, ["."])], lang, [], source="explicit-name")

    local = repo / ".e2e" / "language-profile.json"
    if local.is_file():
        doc = _read_profile(local)
        doc["source"] = "project-local"
        return doc

    candidates = []
    for lang in ("java", "python", "typescript", "javascript"):
        cand = _detect_candidate(repo, lang, domain_hint, touched_files or [])
        if cand is not None:
            candidates.append(cand)

    if not candidates:
        generic = _profile("unknown", ["."], test_substance=False, scope_scan="none")
        generic["score"] = 0
        return _profile_doc([generic], "unknown", ["no-language-markers"], source="detected")

    candidates.sort(key=lambda c: (-c["score"], -c["touched_score"],
                                   -c["marker_score"], c["roots"][0]))
    profiles = [{k: v for k, v in cand.items()
                 if k not in {"score", "touched_score", "marker_score"}}
                for cand in candidates]
    primary = profiles[0]["language"]
    warnings = []
    if domain_hint and not _domain_matches(domain_hint, primary):
        warnings.append(f"domain-language-mismatch: {domain_hint} domain with {primary} primary")
    return _profile_doc(profiles, primary, warnings, source="detected",
                        domain_hint=domain_hint)


def persist_profile(repo: str | Path, run_dir: str | Path, profile_doc: dict) -> tuple[dict, Path]:
    repo = Path(repo).resolve()
    run_dir = Path(run_dir)
    if not run_dir.is_absolute():
        run_dir = repo / run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "language-profile.json"
    path.write_text(json.dumps(profile_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    rel = path.relative_to(repo).as_posix()
    binding = {
        "schema": BINDING_SCHEMA,
        "profile_path": rel,
        "primary_language": profile_doc.get("primary_language"),
        "profiles": [p.get("language") for p in profile_doc.get("profiles", [])],
        "source": profile_doc.get("source", "detected"),
    }
    return binding, path


def _load_explicit(repo: Path, explicit: str) -> dict | None:
    candidate = Path(explicit)
    if not candidate.is_absolute():
        candidate = repo / candidate
    if not candidate.is_file():
        return None
    doc = _read_profile(candidate)
    doc["source"] = "explicit-path"
    return doc


def _read_profile(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != SCHEMA:
        raise ValueError(f"language profile schema mismatch: {path}")
    return doc


def _normalize_language(value: str) -> str:
    lang = _ALIASES.get(value.lower(), value.lower())
    if lang not in _SUPPORTED:
        raise ValueError(f"unsupported language profile: {value}")
    return lang


def _detect_candidate(repo: Path, lang: str, domain_hint: str | None,
                      touched_files: list[str]) -> dict | None:
    marker_score = 0
    roots: set[str] = set()
    for marker in _STRONG_MARKERS.get(lang, ()):
        if (repo / marker).exists():
            marker_score += 250
            roots.add(".")
    for marker in _PACKAGE_MARKERS.get(lang, ()):
        if (repo / marker).exists():
            marker_score += 125
            roots.add(".")
    if (lang == "javascript" and (repo / "package.json").exists()
            and not (repo / "tsconfig.json").exists()
            and not _has_files(repo, (".ts", ".tsx"))):
        marker_score += 125
        roots.add(".")

    file_count = 0
    touched_score = 0
    exts = _EXTENSIONS[lang]
    for path in repo.rglob("*"):
        if not path.is_file() or _skip(path):
            continue
        if path.suffix.lower() not in exts:
            continue
        file_count += 1
        rel = path.relative_to(repo).as_posix()
        roots.add(_root_for(rel, lang))
    for rel in touched_files:
        if Path(rel).suffix.lower() not in exts:
            continue
        touched_score += 200 if any(h in rel for h in _TEST_HINTS) else 100
        roots.add(_root_for(Path(rel).as_posix(), lang))
    touched_score = min(touched_score, 5000)
    if marker_score == 0 and file_count == 0 and touched_score == 0:
        return None
    if lang in {"java", "python"} and any(root != "." for root in roots):
        roots.discard(".")
    domain_score = 60 if _domain_matches(domain_hint, lang) else 0
    score = touched_score + domain_score + marker_score + min(file_count, 50)
    prof = _profile(lang, sorted(roots) or ["."])
    prof.update({"score": score, "touched_score": touched_score, "marker_score": marker_score})
    return prof


def _skip(path: Path) -> bool:
    return any(part in {".git", "node_modules", "__pycache__"} for part in path.parts)


def _has_files(repo: Path, extensions: tuple[str, ...]) -> bool:
    for path in repo.rglob("*"):
        if path.is_file() and not _skip(path) and path.suffix.lower() in extensions:
            return True
    return False


def _root_for(rel: str, lang: str) -> str:
    parts = Path(rel).parts
    if not parts:
        return "."
    if lang == "java":
        if len(parts) >= 4 and parts[:3] in {
            ("src", "main", "java"),
            ("src", "test", "java"),
        }:
            return "/".join(parts[:3])
        return parts[0] if len(parts) > 1 else "."
    if lang == "python":
        if parts[0] in {"src", "test", "tests"}:
            return parts[0]
        return parts[0] if len(parts) > 1 else "."
    if lang in {"typescript", "javascript"} and parts[0] in {"src", "test", "tests"}:
        return parts[0]
    if len(parts) > 1 and parts[0] not in {"src", "test", "tests"}:
        return parts[0]
    return "."


def _domain_matches(domain_hint: str | None, lang: str) -> bool:
    if domain_hint == "frontend":
        return lang in {"javascript", "typescript"}
    if domain_hint == "backend":
        return lang in {"java", "python"}
    return False


def _profile(language: str, roots: list[str], *, test_substance: bool = True,
             scope_scan: str | None = None) -> dict:
    runners = {
        "java": ["maven", "gradle"],
        "python": ["pytest", "unittest"],
        "typescript": ["vitest", "playwright", "jest"],
        "javascript": ["vitest", "playwright", "jest"],
        "unknown": [],
    }[language]
    managers = {
        "java": [],
        "python": [],
        "typescript": ["npm", "pnpm", "yarn"],
        "javascript": ["npm", "pnpm", "yarn"],
        "unknown": [],
    }[language]
    if scope_scan is None:
        scope_scan = "component" if language in {"typescript", "javascript"} else "module"
    return {
        "language": language,
        "roots": roots,
        "test_runners": runners,
        "package_managers": managers,
        "capabilities": {
            "command_replay": language != "unknown",
            "test_substance": test_substance and language != "unknown",
            "scope_scan": scope_scan,
            "dependency_graph": language == "java",
            "browser_evidence": "optional" if language in {"typescript", "javascript"} else "none",
        },
    }


def _profile_doc(profiles: list[dict], primary: str, warnings: list[str], *,
                 source: str, domain_hint: str | None = None) -> dict:
    doc = {
        "schema": SCHEMA,
        "profiles": profiles,
        "primary_language": primary,
        "warnings": warnings,
        "source": source,
    }
    if domain_hint:
        doc["domain_hint"] = domain_hint
    return doc
