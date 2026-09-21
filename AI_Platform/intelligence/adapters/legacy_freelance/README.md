# Legacy Freelance Adapter

This adapter is metadata only. It does not copy or modify the legacy Freelance
Skill Library or Job Runner.

Current source observed during Phase 1:

- Legacy workspace: `<USERPROFILE>\Documents\Codex\2026-09-11\openclaw-openclaw-openclaw-codex-ai-1`
- Skill: `skills/approved/excel-merge`
- Registry: `skills/registry.json`
- Approval history: `skills/approval_history.json`
- Accepted experience: `experience/accepted/exp_excel_source_integrity_001.md`
- Regression test: `skills/approved/excel-merge/tests/test_regression.py`

The Intelligence Layer stores a governed representation and points back to this
legacy source. The legacy runner remains the execution authority until a later
phase explicitly approves an adapter integration.
