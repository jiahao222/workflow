# Architecture and Design Tradeoffs

The offline demonstration implements the five-stage pipeline:

`analyze -> storyboard -> prompts -> render -> deliver`

It accepts only a fictional JSON story brief. Upstream content can be provided by authorized external channels, but retrieval implementations are intentionally excluded.

## Durable queue

- A SQLite task queue tracks workflow state and per-stage payloads.
- `BEGIN IMMEDIATE` serializes claims to prevent double ownership by competing workers.
- Every claim grants a bounded lease, renewable by the lease owner.
- Expired leases may be reclaimed; stale worker completions are rejected.
- Stage completion and scheduling of the next stage share one transaction.
- A unique constraint on `(workflow_id, stage)` prevents duplicate stage records.
- Retriable failures use bounded backoff; exhausted retries mark the workflow failed.
- Cancellation invalidates any outstanding task leases.

## Constraints

This single-host demo has synchronous workers and does not perform real AI inference. A production architecture would require independent heartbeats during long jobs, object storage, access control, tenant isolation, metrics, and external provider adapters. Those implementations are intentionally excluded to protect private projects.
