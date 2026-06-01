# Honest Dispatch Lifecycle Design

## Problem

The dispatcher must not let the coordinator claim that a worker is running or complete unless a runtime worker was actually requested and acknowledged.

The original single-slot dispatch flow allowed `dispatch-complete` to rely on the latest `dispatch` field. In multi-worker and review flows this created two risks:

- A later task could overwrite the latest dispatch slot and let another task complete against the wrong runtime proof.
- A task that was only claimed in `agent-schedule.json` could be completed without being dispatched and acknowledged by the runtime.

## Invariants

- `dispatch-beat` and `dispatch-next` create dispatcher-owned spawn requests; they do not perform worker work locally.
- `dispatch-ack` records runtime confirmation for the exact task id.
- `dispatch-complete` must match the completing task id to `dispatches[task_id]`.
- Completion is allowed only from a confirmed `worker_running` dispatch with a worker handle or session proof.
- The legacy top-level `dispatch` field remains as a latest/current compatibility view only.

## State Shape

```json
{
  "dispatch": {
    "status": "worker_running",
    "current_task_id": "T01",
    "current_agent": "code-developer-service",
    "worker_handle": "runtime-worker-id"
  },
  "dispatches": {
    "T01": {
      "status": "worker_running",
      "current_task_id": "T01",
      "current_agent": "code-developer-service",
      "worker_handle": "runtime-worker-id"
    }
  }
}
```

## Completion Rule

`dispatch-complete` blocks when:

- no matching `dispatches[task_id]` exists;
- matching dispatch is not `worker_running`;
- the completing agent does not match the dispatched agent;
- no runtime confirmation proof is present.

This keeps R1/R2/R3 reviewer tasks and service code tasks symmetric: all dispatcher-generated workers must be spawned, acknowledged, then completed.

