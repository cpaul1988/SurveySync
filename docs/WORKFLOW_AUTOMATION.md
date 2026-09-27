# SurveySync Workflow Automation

## Purpose

SurveySync 9.4 adds a small project-scoped declarative workflow engine inspired by
the trigger/action separation used by Block's Apache-2.0 Buzz project.

The engine is intentionally SurveySync-native. It does not embed Buzz's relay,
database, agent runtime or network architecture.

## Storage

Workflow definitions are stored in:

`.surveysync/workflows.yaml`

Workflow run state is stored as one JSON file per run in:

`.surveysync/workflow_runs/`

This makes definitions reviewable and keeps a waiting approval resumable without
restarting earlier actions.

## Supported triggers

- `manual`
- `project_opened`
- `source_imported`
- `qa_completed`
- `export_completed`
- `deliverable_created`

Project-open and source-import triggers are dispatched at their central SurveySync
boundaries. QA/export/deliverable triggers are dispatched by the shared operations
routes used by the application UI.

A workflow failure never rolls back the normal SurveySync operation that emitted the
trigger.

## Supported actions

### Automatic actions

- `run_qa` — run Project Health.
- `run_export_profile` — create files from a saved export profile.
- `create_review_item` — add a QASync review item.

### Approval-gated actions

- `build_deliverable` — build/register a FINAL deliverable package.
- `send_notification` — send a configured stakeholder email.

Approval requirements are enforced by the engine and cannot be turned off by a YAML
field.

When an approval-gated action is reached, the run becomes `WAITING_APPROVAL`.
The run records the exact action index, type, parameters and description. Approval
continues from that action; rejection ends the run as `REJECTED`.

## Example YAML

```yaml
version: 1
workflows:
  - workflow_id: preflight_delivery
    name: Preflight delivery
    enabled: true
    trigger: manual
    description: Run health, export points, then wait for package approval.
    actions:
      - type: run_qa
        params: {}
      - type: run_export_profile
        params:
          profile_id: client_deliverable
      - type: build_deliverable
        params:
          profile_id: client_deliverable
          label: Reviewed workflow package
```

The final action always pauses for human approval even if
`requires_approval: false` is manually added to YAML.

## API

- `GET /api/v9/workflows/status`
- `GET /api/v9/workflows`
- `POST /api/v9/workflows`
- `POST /api/v9/workflows/delete`
- `POST /api/v9/workflows/run`
- `POST /api/v9/workflows/approve`
- `GET /api/v9/workflow-runs`
- `POST /api/v9/workflows/dispatch`
- `GET /api/v9/workflows/export-yaml`
- `POST /api/v9/workflows/import-yaml`

## Audit behavior

SurveySync records workflow definition changes, run starts, approval waits,
approvals/rejections, failures and completions in the existing tamper-evident project
audit chain.

Review items are ordinary QASync issues, so they surface in the existing Review
Center.

## Safety boundary

The workflow engine is not permitted to introduce arbitrary shell commands, Python
expressions, dynamically imported functions, or user-supplied executable code.
Unknown triggers and actions fail closed.

The first version also avoids actions that silently edit raw observations, mark points
reviewed, accept control, restore revisions, commit staged imports, or otherwise make
professional survey decisions.

## Upstream reference

Buzz: https://github.com/block/buzz

License: Apache License 2.0

SurveySync uses the declarative workflow concept as architecture inspiration only; no
Buzz Rust source is embedded in the workflow engine.
