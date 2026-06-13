"""First-class track ledger: fork materialization + projection (pure, no I/O)."""
from e2e_harness import pipeline
from e2e_harness.core import multitrack, module_plan


def _plan(*mods):
    return {"schema": module_plan.SCHEMA, "modules": list(mods)}


def _mod(mid, deps=()):
    return {"id": mid, "name": f"{mid} svc", "depends_on": list(deps), "acceptance_ids": ["AC-001"]}


def _expanded(*mods):
    base = pipeline.build_spine("standard")
    return multitrack.expand(base, _plan(*mods)), _plan(*mods)


def test_module_chains_groups_phases_per_module_in_spine_order():
    spine, _ = _expanded(_mod("auth"), _mod("billing", deps=["auth"]))
    chains = multitrack.module_chains(spine)
    assert list(chains) == ["auth", "billing"]
    assert [p.name for p in chains["auth"]] == ["RED#auth", "IMPLEMENTED#auth", "REVIEWED#auth"]
    assert [p.name for p in chains["billing"]] == ["RED#billing", "IMPLEMENTED#billing", "REVIEWED#billing"]


def test_fork_tracks_materializes_one_track_per_module():
    spine, mplan = _expanded(_mod("auth"), _mod("billing", deps=["auth"]))
    tracks = multitrack.fork_tracks(spine, mplan)
    assert set(tracks) == {"auth", "billing"}
    assert tracks["auth"] == {
        "module_id": "auth", "current_phase": "RED#auth",
        "dispatch": "pending", "depends_on": [], "complete": False,
    }
    assert tracks["billing"]["depends_on"] == ["auth"]
    assert tracks["billing"]["current_phase"] == "RED#billing"


def test_fork_tracks_without_plan_falls_back_to_linear_dependencies():
    spine, _ = _expanded(_mod("auth"), _mod("billing"))
    tracks = multitrack.fork_tracks(spine, None)
    # plan-less band serializes (matches the legacy flattened walk)
    assert tracks["auth"]["depends_on"] == []
    assert tracks["billing"]["depends_on"] == ["auth"]


def _tracks(**by_mid):
    """Build a tracks dict from {mid: (current_phase, complete, depends_on)}."""
    out = {}
    for mid, (cur, complete, deps) in by_mid.items():
        out[mid] = {"module_id": mid, "current_phase": cur, "dispatch": "pending",
                    "depends_on": list(deps), "complete": complete}
    return out


def test_active_track_ids_excludes_complete_and_dep_blocked():
    tracks = _tracks(
        auth=("RED#auth", False, []),
        reports=("RED#reports", False, []),
        billing=("RED#billing", False, ["auth"]),
    )
    assert multitrack.active_track_ids(tracks) == ["auth", "reports"]


def test_active_track_ids_unblocks_dependent_when_dependency_complete():
    tracks = _tracks(
        auth=("REVIEWED#auth", True, []),
        billing=("RED#billing", False, ["auth"]),
    )
    assert multitrack.active_track_ids(tracks) == ["billing"]


def test_project_leading_phase_picks_least_advanced_active_track():
    tracks = _tracks(
        auth=("IMPLEMENTED#auth", False, []),   # rank 1
        reports=("RED#reports", False, []),      # rank 0 -> leads
    )
    assert multitrack.project_leading_phase(tracks, "module_band", None) == "RED#reports"


def test_project_leading_phase_tie_breaks_by_track_order():
    tracks = _tracks(
        auth=("RED#auth", False, []),
        reports=("RED#reports", False, []),
    )
    assert multitrack.project_leading_phase(tracks, "module_band", None) == "RED#auth"


def test_project_leading_phase_returns_singleton_outside_band():
    assert multitrack.project_leading_phase({}, "prologue", "PLANNED") == "PLANNED"
    assert multitrack.project_leading_phase({}, "epilogue", "VERIFIED") == "VERIFIED"
