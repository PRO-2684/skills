---
name: dependency-archaeology
description: Resolve dependency conflicts and make project environments reproducible by discovering existing Docker, Conda, pip, uv, Poetry, PDM, npm/yarn/pnpm, or other environment/dependency files; pin exact package versions; regenerate or verify lockfiles; protect git-untracked environment/code changes by warning and asking before editing them; and ask the user before creating a new environment specification when none exists. Use when Codex is asked to fight local environment problems, investigate dependency history, fix dependency installation failures, pin versions, repair broken lockfiles, or make setup repeatable across machines, containers, or CI.
---

# Dependency Archaeology

## Workflow

1. Inventory the repository before changing anything.
   - Search for environment files with `rg --files`, including:
     `Dockerfile`, `docker-compose*.yml`, `compose*.yaml`, `.devcontainer/*`,
     `environment.yml`, `environment.yaml`, `conda-lock.yml`, `requirements*.txt`,
     `constraints*.txt`, `pyproject.toml`, `uv.lock`, `poetry.lock`, `pdm.lock`,
     `Pipfile`, `Pipfile.lock`, `setup.py`, `setup.cfg`, `package.json`,
     `package-lock.json`, `npm-shrinkwrap.json`, `yarn.lock`, `pnpm-lock.yaml`,
     `Gemfile`, `Gemfile.lock`, `go.mod`, `go.sum`, `Cargo.toml`, `Cargo.lock`,
     `renv.lock`, `DESCRIPTION`, `Makefile`, CI config, and README setup sections.
   - Identify the canonical environment source. Prefer the lockfile plus its manifest
     when both exist; otherwise prefer the file documented by README/CI/devcontainer.
   - Note tool versions when encoded in files, such as Python, Node, CUDA, Conda,
     base Docker image tags, package manager versions, or `.tool-versions`.
   - Check `git status --short` and whether candidate environment files are tracked.
     Warn and ask before changing environment files, lockfiles, scripts, or code that
     git will not record, such as untracked files, ignored files, generated files
     outside the repository, or files in an unversioned virtual environment.

2. If no dependency or environment file exists, stop and ask the user how to proceed.
   - Briefly list what was searched.
   - Propose creating one canonical file suitable for the project, such as
     `pyproject.toml` plus `uv.lock`, `requirements.txt` plus `constraints.txt`,
     `environment.yml`, or a `Dockerfile`.
   - Do not invent a new environment format without user approval.

3. Reproduce the failure with the existing toolchain.
   - Run the install or resolver command the project already uses, such as
     `uv sync`, `pip install -r requirements.txt`, `conda env create -f environment.yml`,
     `poetry install`, `pdm install`, `npm ci`, `pnpm install --frozen-lockfile`,
     or the documented setup target.
   - Capture the first real conflict, not just the final summary. Look for incompatible
     version ranges, missing wheels, unsupported Python/Node versions, platform markers,
     CUDA or system-library constraints, and stale transitive pins.
   - If network access or approvals block verification, report that explicitly and
     continue with static analysis only when useful.

4. Resolve conflicts conservatively.
   - Preserve the project's chosen tooling and file ownership.
   - Change the smallest set of direct dependencies needed to satisfy all constraints.
   - Prefer exact pins for reproducibility. Use `==` in pip constraints, fully resolved
     lockfiles for uv/Poetry/PDM/npm/pnpm/yarn, exact Conda build pins when required,
     and immutable Docker image tags or digests when practical.
   - Avoid broad upgrades, deleting constraints, or mixing package managers unless the
     existing setup is already mixed and documented.
   - Keep platform-specific constraints explicit with markers rather than hiding them.

5. Regenerate and verify the reproducible artifact.
   - Use the native resolver to update lockfiles. Examples:
     `uv lock`, `poetry lock`, `pdm lock`, `pip-compile`, `conda-lock`,
     `npm install --package-lock-only`, `pnpm install --lockfile-only`, or
     `yarn install --mode=update-lockfile`.
   - Verify with the frozen/sync install command.
   - Before running a long test command, create and run a minimal reproducible test
     that exercises the dependency conflict or import/runtime path directly. Prefer a
     targeted import smoke test, resolver dry run, single-package command, one focused
     unit test, or tiny script over a full suite, training job, Docker build, or CI-like
     command.
   - Run the full documented test command only when it is reasonably fast or when the
     minimal repro cannot prove the environment fix. If skipping a long command, state
     the expected command and why the minimal repro is sufficient.
   - If the repository has Docker/devcontainer/CI setup, ensure the pinned files and
     lockfiles are the ones those paths consume.

6. Prepare the handoff.
   - If the environment was successfully reproduced, the relevant tests passed, and
     the user has nothing staged, stage the dependency/environment changes and provide
     a concise commit message.
   - If the user already has staged changes, do not alter the index. Report the
     unstaged changes this work produced and provide a commit message the user can use.
   - If reproduction or tests did not pass, do not stage changes unless the user
     explicitly asks.

## Output Expectations

- State which environment files were found and which one is canonical.
- Explain the conflict root cause in terms of exact packages and version constraints.
- List changed files and why each change is needed.
- Mention any untracked or ignored files that were intentionally left untouched or
  edited with user approval.
- Include the verification commands run and their result, distinguishing minimal
  reproducible tests from any skipped long-running commands.
- State whether changes were staged, and include the proposed commit message when
  staging criteria are met.
- If exact reproducibility cannot be achieved, identify the remaining unpinned inputs
  such as OS packages, base image tags, system drivers, CUDA, Python, or Node.
