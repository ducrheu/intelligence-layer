# excel-merge

This is a Phase 1 governed metadata adapter for the existing approved legacy
Freelance Skill. It is not an execution copy and does not replace the legacy
Job Runner.

## Contract

- Inspect workbook names, sheets, headers, and data-row counts.
- Prefer a worksheet named `data`; do not assume workbook order is data order.
- Confirm compatible schemas.
- Preserve source files.
- Run the legacy task script and independent machine QA.
- Stop at `READY_FOR_HUMAN` until a person approves delivery.

## Required QA

- Output exists and is non-empty.
- Output schema and row count match expectations.
- Every source workbook remains readable.
- Every source hash is unchanged.
