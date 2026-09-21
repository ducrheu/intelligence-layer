# Lifecycle

## Knowledge and Source

```text
candidate -> validated -> approved -> stale -> validated
approved -> deprecated -> archived
```

## Experience

```text
candidate -> validated -> approved -> archived
```

## Skill

```text
candidate -> experimental -> validated -> approved
approved -> deprecated -> archived
```

There is no direct `candidate -> approved` transition. `request_promotion`
only records a pending request. `approve` is a separate operation requiring
the `approve` scope.

## Versioning

Versions use `MAJOR.MINOR.PATCH`. A replacement should use `supersedes` and
the old artifact records `superseded_by`. The old version remains in Git for
audit and rollback.
