---
name: cyber-mysophobia
description: "Use when Codex should modernize aggressively: prefer ideal architecture and API design, remove legacy/unused code, disregard compatibility, avoid outdated dependencies, reject lint/type errors, avoid suppression hacks, and replace silent fallbacks with explicit failures. Trigger on Cyber Mysophobia, uncompromising cleanup, modernization, API redesign, dependency refresh, legacy removal, lint/type strictness, explicit error handling, or compatibility-disregarding refactors."
---

# Cyber Mysophobia

Prefer clean target design over compatibility. Delete rot. Break old contracts when cleaner.

## Rules

- Design first: idiomatic arch, narrow APIs, minimal surface.
- Compatibility expendable unless user explicitly requires it.
- Delete unused code, dead branches, shims, aliases, deprecated paths, obsolete tests.
- Update all local callers to new contract; do not keep wrappers for old shape.
- Use current maintained deps; remove stale dep imports/config/lockfile/docs.
- Lint/type errors intolerable. Fix every diagnostic, however small.
- Avoid `# type: ignore`, lint disables, broad allowlists, fake casts. Use only when unavoidable; explain.
- Hate silent fallback. No swallowed errors, hidden defaults, temp workaround branches.
- Prefer explicit error with precise fix path.
- Preserve correctness, security, data integrity, explicit user constraints.

## Workflow

1. Pick ideal new shape.
2. Move callers.
3. Delete old surface.
4. Replace fallbacks with explicit errors; fix root cause.
5. Update tests for new contract.
6. Run formatter, linter, type checker, relevant tests.

## Sub-Guidelines

Language-specific sub-guidelines under `langs/`, with slug as file stem. List and read based on project language.

## Communication

State target design, deletions, breaking changes, verification, remaining explicit failures.
