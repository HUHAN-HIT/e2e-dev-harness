# Phase Skill Capabilities Contract

The control plane is the single source of truth for task capability metadata.

## Capability source
- `agent_roles.PHASE_SKILL_CAPABILITIES` maps phase -> (`required_skill`, `required_skill_path`, `skill_reference_set`).
- `engine/control_plane.py` injects these fields in `_normalize_task` and `task_contract`, so every task entering the control plane (planner expansion, legacy import, repair task) carries them.
- `_schedule_projection()` copies tasks verbatim; the projected `agent-schedule.json` therefore carries the fields without any schedule-only write path.

## Propagation
1. Control-plane task -> schedule projection.
2. `context_pack.build_pack()` -> `required_skill`, `required_skill_path`, `skill_reference_set`.
3. `dispatcher.task_prompt()` -> "Required worker skill" section naming the skill file and reference set.
4. `runtime_adapters.RuntimeAdapter.spawn()` -> top-level (and Codex `arguments`) skill metadata.
5. Generated role templates -> "Required Worker Skill" section.

## Backward compatibility and tiers
- Fields are additive and optional. Tasks whose phase is not in the map (coordination, minimal-tier bespoke phases) carry empty capability fields and are never blocked.
- Legacy schedules without these fields claim, dispatch, and complete unchanged.
- `agent_scheduler.capability_blockers()` validates fields only when present.

## Authority
- Gates and scripts remain authoritative. Worker skills describe stage-local behavior only and never replace `clarify`, `gate`, `dispatch-complete`, `handoff`, `ac-progress`, `guard`, or strict completion evidence.
