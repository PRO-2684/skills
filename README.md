# Skills

My personal skills gallery. Primarily used with Codex. Should also work with other agents.

## Install

To install skills on Codex:

```
$skill-installer Install from PRO-2684/skills, path skills/cyber-mysophobia
```

Or using the script directly:

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py --repo PRO-2684/skills --path skills/cyber-mysophobia
```

Alternatively, clone this repo and link the skills:

```bash
ln -s path/to/repo/skills/cyber-mysophobia ~/.codex/skills/cyber-mysophobia
```

## List

| Name                                                      | Slug                     | Desc                                                                    | Pic?                                                              |
| --------------------------------------------------------- | ------------------------ | ----------------------------------------------------------------------- | ----------------------------------------------------------------- |
| [Cyber Mysophobia](./skills/cyber-mysophobia)             | `cyber-mysophobia`       | Prefer idiomatic and modern approaches, disregarding compatibility      | [cyber-mysophobia.png](./images/cyber-mysophobia.png)             |
| [Dependency Archaeology](./skills/dependency-archaeology) | `dependency-archaeology` | Resolve dependency conflicts and make project environments reproducible | [dependency-archaeology.png](./images/dependency-archaeology.png) |
| [Long Wait](./skills/long-wait)                           | `long-wait`              | Resume the same Codex thread after a long-running external condition    | [long-wait.png](./images/long-wait.png)                           |
| [Search Papers](./skills/search-papers)                   | `search-papers`          | Find conference papers before arXiv preprints                           | [search-papers.png](./images/search-papers.png)                   |

<details><summary>Archived</summary>

These skills are archived and not actively used personally:

| Name                      | Slug     | Reason                                      | Pic?                              |
| ------------------------- | -------- | ------------------------------------------- | --------------------------------- |
| [Debate](./skills/debate) | `debate` | Kinda useless; should use `grill-with-docs` | [debate.png](./images/debate.png) |

</details>

## Imported Skills

Imported from [mattpocock/skills](https://github.com/mattpocock/skills), before the skills became dependent on others:

- [grill-with-docs](./imported/grill-with-docs)
- [handoff](./imported/handoff)
- [improve-codebase-architecture](./imported/improve-codebase-architecture)
- [setup-matt-pocock-skills](./imported/setup-matt-pocock-skills)
