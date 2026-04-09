---
name: project-expert
description: Build expert knowledge bases from project management data — scan issues, explore topics, extract beliefs
argument-hint: "[init|scan|explore|topics|propose-beliefs|accept-beliefs|status]"
allowed-tools: Bash(project-expert *), Bash(uv run project-expert *), Bash(uvx *ftl-project-expert*), Read, Grep, Glob
---

# Project Expert

Build expert knowledge bases from project management data (GitHub, GitLab, Jira) by combining issue exploration with belief extraction.

## How to Run

Try these in order until one works:
1. `project-expert $ARGUMENTS` (if installed via `uv tool install`)
2. `uv run project-expert $ARGUMENTS` (if in the repo with pyproject.toml)
3. `uvx --from git+https://github.com/benthomasson/ftl-project-expert project-expert $ARGUMENTS` (fallback)

## Typical Workflow

```bash
project-expert init github owner/repo --domain "Payment platform"
project-expert scan                           # fetch issues, build overview, populate queue
project-expert explore                        # explore next topic
project-expert explore --pick 1,3,8           # explore multiple by index (stable indices)
project-expert explore --skip                 # skip one
project-expert topics                         # see exploration queue
project-expert propose-beliefs                # extract beliefs from entries
# edit proposed-beliefs.md: mark [ACCEPT] or [REJECT]
project-expert accept-beliefs                 # import accepted beliefs
project-expert status                         # dashboard
```

## Commands

- `init <platform> <target>` — Bootstrap knowledge base (github/gitlab/jira)
- `scan [--limit N] [--labels L] [--state S] [--jql Q]` — Fetch and analyze issues
- `explore [--skip] [--pick N[,N,...]] [--loop N]` — Work through topic queue
- `topics [--all]` — Show exploration queue
- `propose-beliefs [--batch-size N]` — Extract beliefs from entries
- `accept-beliefs [--file F]` — Import accepted beliefs (uses `reasons` if installed, falls back to `beliefs`)
- `status` — Dashboard

## Natural Language

If the user says:
- "analyze this project" → `project-expert init github owner/repo && project-expert scan`
- "what should I look at next" → `project-expert explore`
- "deep dive into issue 42" → `project-expert explore --pick N` (where N is the topic index for that issue)
- "extract what we've learned" → `project-expert propose-beliefs`
- "how far along are we" → `project-expert status`

## Supported Platforms

- **GitHub** — uses `gh` CLI
- **GitLab** — uses `glab` CLI
- **Jira** — uses REST API (needs JIRA_URL, JIRA_USER, JIRA_TOKEN env vars)

## Belief Storage

When `ftl-reasons` is installed (`reasons` CLI on PATH), `accept-beliefs` writes directly to `reasons.db` and re-exports `beliefs.md` and `network.json`. When only `ftl-beliefs` is installed, it writes to `beliefs.md` directly.
