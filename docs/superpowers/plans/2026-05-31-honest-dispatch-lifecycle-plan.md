# Honest Dispatch Lifecycle Plan

## Scope

Repair the dispatcher lifecycle so repo source, tests, and installed skill copies agree on the same honesty invariant.

## Changes

1. Add a regression proving `dispatch-complete` blocks a task that was claimed but never dispatched.
2. Require `dispatch-complete` to find the matching task dispatch slot.
3. Require status `worker_running` and runtime acknowledgement proof before completing.
4. Preserve legacy `dispatch` as a compatibility view while treating `dispatches[task_id]` as authoritative.
5. Keep reviewer tasks symmetric with code tasks: R1/R2/R3 dispatches can auto-confirm from runtime Task hooks, but cannot complete without confirmation.
6. Sync the fixed skill into installed runtime locations with `node tools/install-e2e-dev-harness.mjs --sync --yes`.

## Verification

- `python -m unittest discover -s tests -p test_orchestration.py -k dispatch`
- `python -m unittest discover -s tests -p test_orchestration.py`
- `python -m unittest discover -s tests -p test_e2e_dev_harness_scripts.py`
- `python -m unittest discover -s tests`

## Follow-Up

The dispatcher fix closes the honesty gap. Further hardening should centralize lifecycle transitions in `run_state.py` and reduce shell write detection dependence on free-text command regexes.

