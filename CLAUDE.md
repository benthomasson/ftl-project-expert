# CLAUDE.md

## Project

`ftl-project-expert` — CLI tool that builds expert knowledge bases from project management data (GitHub, GitLab, Jira). Uses LLMs to scan issues, explore topics, extract beliefs, and derive new insights.

## Dev Setup

```bash
uv sync
```

## Issue Fix Process

When fixing a GitHub issue, follow this workflow:

1. **Read the issue** — `gh issue view <number> --repo benthomasson/ftl-project-expert --comments`
2. **Checkout main and pull latest** — `git checkout main && git pull`
3. **Fix on a dedicated branch from main** — branch name should reflect the fix (e.g. `fix-export-json-corruption`)
4. **Commit and push**, then open a PR referencing the issue (`Fixes #N`)
5. **Run code review with comment** — `code-review review-loop --pr <url> --github-issue <issue-url> --comment`
6. **Address review concerns** — commit and push follow-up fixes
7. **Re-review** until concerns are resolved or acknowledged as out-of-scope
8. **Squash-merge** — `gh pr merge <number> --squash --delete-branch`
9. **Checkout main and pull latest** — `git checkout main && git pull`
10. **Reinstall uv tool** — `uv tool install --reinstall -e .`
