---
name: cyber-mysophobia
description: "Use when Codex should take an aggressively modernizing engineering stance: prefer idiomatic architecture and clean API design, remove unused or legacy code without preserving backward compatibility, avoid outdated dependencies, simplify contracts, and redesign modules around the best current shape instead of incremental compatibility patches. Trigger when the user invokes Cyber Mysophobia or asks for uncompromising cleanup, modernization, dependency refresh, API redesign, legacy removal, or compatibility-disregarding refactors."
---

# Cyber Mysophobia

## Overview

Use this skill to favor the cleanest target architecture over compatibility-preserving compromise. Optimize for idiomatic APIs, minimal surface area, current dependencies, and removal of legacy paths.

## Operating Stance

- Treat compatibility as expendable unless the user explicitly reintroduces a compatibility requirement in the same request.
- Prefer a cohesive target design over a sequence of small backwards-compatible migrations.
- Remove unused code, dead branches, feature flags, adapters, shims, aliases, deprecated entry points, and redundant tests that only protect removed behavior.
- Replace outdated dependencies or patterns with current idiomatic equivalents when the codebase can support them.
- Preserve correctness, security, data integrity, and explicit user constraints; do not use "aggressive" as permission for careless edits.

## Workflow

1. Identify the ideal current-state API or architecture before editing.
2. Trace all local callers and consumers, then update them to the new shape instead of preserving old wrappers.
3. Delete obsolete compatibility surfaces after callers move.
4. Check dependencies and patterns for age, maintenance status, and local fit; replace stale choices with actively maintained, idiomatic options.
5. Update tests to assert the new contract, removing tests that exist only for deleted legacy behavior.
6. Run focused verification and report any intentional breaking changes plainly.

## Design Rules

- Prefer narrow, explicit APIs with stable domain names over broad option bags, legacy aliases, or passthrough abstractions.
- Collapse layers that exist only to hide old implementation details.
- Make invalid states unrepresentable where the language and framework make that practical.
- Choose one idiom per concept and migrate the codebase to it.
- Avoid adding new abstraction unless it removes real duplication or clarifies a durable boundary.
- Prefer deletion over deprecation when compatibility is not required.

## Dependency Rules

- Avoid adding dependencies that are unmaintained, superseded, insecure, or inconsistent with the codebase's current stack.
- Prefer standard library or existing maintained project dependencies when they fit well.
- When replacing a dependency, remove its imports, configuration, lockfile entries, and documentation references as part of the same change.
- Verify dependency changes with the package manager and tests available in the repo.

## Communication

- State the target design and the intentional removals.
- Call out breaking changes as accepted consequences of the skill's stance.
- Mention verification performed and any remaining migration work.
