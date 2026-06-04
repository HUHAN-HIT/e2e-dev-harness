"""Install command facade."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path

from e2e_harness.cli.status import write_status


def _legacy_cli():
    return importlib.import_module("e2e_dev_harness")


def run(
    repo: Path,
    target: str = "codex",
    install_root: Path | None = None,
    source_skill_dir: Path | None = None,
    runtime: str = "claude",
    full: bool = False,
    yes: bool = False,
    install_external: bool = False,
    skip_external: bool = False,
    with_hooks: bool = False,
    doctor: bool = False,
    status_file: Path | None = None,
) -> tuple[int, dict]:
    return run_from_args(
        argparse.Namespace(
            repo=repo,
            target=target,
            install_root=install_root,
            source_skill_dir=source_skill_dir,
            runtime=runtime,
            full=full,
            yes=yes,
            install_external=install_external,
            skip_external=skip_external,
            with_hooks=with_hooks,
            doctor=doctor,
            status_file=status_file,
        )
    )


def run_from_args(args) -> tuple[int, dict]:
    legacy = _legacy_cli()
    repo = legacy.as_repo(args.repo)
    full = bool(getattr(args, "full", False))
    target = "all" if full else args.target
    targets = legacy.install_targets(target)
    install_root = Path(args.install_root or Path.home()).resolve()
    source_skill = Path(args.source_skill_dir or legacy.SCRIPT_DIR.parent).resolve()
    install_external = bool(getattr(args, "install_external", False) or (full and not getattr(args, "skip_external", False)))
    with_hooks = bool(getattr(args, "with_hooks", False) or full)
    run_doctor = bool(getattr(args, "doctor", False) or full)
    runtime = getattr(args, "runtime", "claude")
    actions: list[dict] = []
    action_results: list[dict] = []
    blockers: list[str] = []
    installed_skills: list[dict] = []

    if not (source_skill / "SKILL.md").exists():
        blockers.append(f"Source skill is missing SKILL.md: {source_skill}")

    skill_targets = [
        {"target": name, "path": str(install_root.joinpath(*legacy.INSTALL_TARGETS[name]))}
        for name in targets
    ]
    actions.append({
        "id": "copy-skill",
        "description": "Copy e2e-dev-harness into runtime skill directories.",
        "targets": skill_targets,
    })

    if install_external:
        if not legacy.shutil.which("gitnexus"):
            actions.append({"id": "install-gitnexus", "command": "npm install -g gitnexus", "cwd": str(repo)})
        if not legacy.shutil.which("graphify"):
            actions.append({
                "id": "install-graphify",
                "command": f"{legacy.sys.executable} -m pip install --user graphifyy",
                "cwd": str(repo),
            })

    if with_hooks:
        actions.append({
            "id": "install-hooks",
            "description": f"Install {runtime} hook configuration into the current project.",
            "command": f"{legacy.sys.executable} {legacy.SCRIPT_DIR / 'install_hooks.py'} {repo} --runtime {runtime} --json",
            "cwd": str(repo),
        })

    if run_doctor:
        actions.append({
            "id": "doctor",
            "description": "Run e2e-dev-harness doctor against the current project.",
            "command": f"{legacy.sys.executable} {Path(legacy.__file__).resolve()} doctor {repo} --json",
            "cwd": str(repo),
        })

    result = {
        "schema": "e2e-dev-harness.install.v1",
        "project_root": str(repo),
        "source_skill_dir": str(source_skill),
        "install_root": str(install_root),
        "targets": targets,
        "full": full,
        "runtime": runtime,
        "executed": bool(args.yes),
        "actions": actions,
        "action_results": action_results,
        "installed_skills": installed_skills,
        "ready": not blockers,
        "blocked_reasons": blockers,
        "warnings": [],
    }

    if result["ready"] and args.yes:
        for skill_target in skill_targets:
            copied = legacy.copy_skill_tree(source_skill, Path(skill_target["path"]))
            installed_skills.append({"target": skill_target["target"], **copied})
        for action in actions:
            if action["id"] == "copy-skill":
                continue
            if action["id"] == "install-hooks":
                hook_result = legacy.install_hooks.install(repo, runtime)
                action_results.append({
                    "action": action["id"],
                    "exit_code": 0 if hook_result["ready"] else 2,
                    "result": hook_result,
                })
            elif action["id"] == "doctor":
                doctor_result = legacy.harness_doctor.evaluate(repo)
                action_results.append({
                    "action": action["id"],
                    "exit_code": 0 if doctor_result["ready"] else 2,
                    "result": doctor_result,
                })
            else:
                command = (
                    ["npm", "install", "-g", "gitnexus"]
                    if action["id"] == "install-gitnexus"
                    else [legacy.sys.executable, "-m", "pip", "install", "--user", "graphifyy"]
                )
                action_results.append({"action": action["id"], **legacy.run_install_command(command, repo)})
            if action_results[-1]["exit_code"] != 0:
                result["ready"] = False
                result["blocked_reasons"].append(f"Action failed: {action['id']}")
                break
    write_status(args.status_file, result)
    return (0 if result["ready"] else 2), result
