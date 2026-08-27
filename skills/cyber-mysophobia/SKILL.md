---
name: cyber-mysophobia
description: "Use when Codex should modernize aggressively: prefer ideal architecture and API design, remove legacy/unused code, disregard compatibility, avoid outdated dependencies, reject lint/type errors, avoid suppression hacks, and replace silent fallbacks with explicit failures. Trigger on Cyber Mysophobia, uncompromising cleanup, modernization, API redesign, dependency refresh, legacy removal, lint/type strictness, explicit error handling, or compatibility-disregarding refactors."
---

# Cyber Mysophobia

Prefer clean target design over compatibility. Delete rot. Break old contracts when cleaner.

## Stance

Clean target shape wins over legacy continuity unless user explicitly requires compatibility. Prefer explicit failure over hidden accommodation.

## Design Rules

- Design first: idiomatic arch, narrow APIs, minimal surface.
- Compatibility expendable unless user explicitly requires it.
- Update all local callers to new contract; do not keep wrappers for old shape.

## Deletion Rules

- Delete unused code, dead branches, shims, aliases, deprecated paths, obsolete tests.
- Use current maintained deps; remove stale dep imports/config/lockfile/docs.

## Diagnostics

- Lint/type errors intolerable. Fix every diagnostic, however small.
- Avoid `# type: ignore`, lint disables, broad allowlists, fake casts. Use only when unavoidable; explain.

## Failure Handling

- Hate silent fallback. No swallowed errors, hidden defaults, temp workaround branches.
- Do not translate obvious runtime errors into lower-fidelity messages. Preserve original errors unless adding specific context or a real fix path.
- Prefer explicit error with precise fix path.

## Guardrails

- Preserve correctness, security, data integrity, explicit user constraints.

## API Shape

- Prefer methods, constructors, or associated functions over public free functions when behavior belongs to a type. Private helper functions are fine when they keep implementation readable without widening public surface.
- Prefer typed domain objects over untyped maps, loose objects, or implicit structure.
- Avoid wildcard imports/import-all forms; import explicit names unless language tooling makes that impractical.
- Prefer explicit contracts over dynamic lookup, reflection, magic defaults, or convention-only coupling.
- For CLI args, prefer dashed form (`--model-path`) over underlined form (`--model_path`).

## Workflow

1. Pick ideal new shape.
2. Move callers.
3. Delete old surface.
4. Replace fallbacks with explicit errors; fix root cause.
5. Update tests for new contract.
6. Run formatter, linter, type checker, relevant tests.

## Language Notes

Language-specific examples and exceptions live under `langs/`, with slug as file stem. List and read based on project language.

## Communication

State target design, deletions, breaking changes, verification, remaining explicit failures.
