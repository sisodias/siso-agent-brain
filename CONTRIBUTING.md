# Contributing

A change belongs here only when it changes shared-state behavior, the API/client contract, schema evolution, or conservative state portability.

Before submitting:

1. State the data or API contract that changes.
2. Add a new immutable migration for schema changes.
3. Extend the disposable live-server receipt in `scripts/check_repo.py`.
4. Confirm public health and errors disclose no host paths, secrets, or records.
5. Run `npm test`.

Adapters and consumers should remain in their own repositories whenever they can version independently.
