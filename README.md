# project-expert

Deep project analysis through belief networks. Systematically scans issue trackers (GitHub, GitLab, Jira), extracts factual beliefs about project state, builds dependency networks, and surfaces risks that status meetings, dashboards, and individual issue views miss.

**What it finds:** Not just overdue tickets, but structural project risks — overloaded teams with no recent closures, epics with hidden blockers, milestones at risk from upstream dependencies, and patterns across issues that only become visible when you build a theory of the project and reason over it.

**How it works:** project-expert fetches issues from your tracker, runs them through an LLM for structured analysis, extracts factual claims into a reason maintenance system, and derives logical consequences across the belief network — surfacing the issues that matter most.

## Install

```bash
uv tool install git+https://github.com/benthomasson/ftl-project-expert
```

Prerequisites — these CLIs must be on your PATH:

- [`entry`](https://github.com/benthomasson/entry) — chronological entry creation
- [`beliefs`](https://github.com/benthomasson/beliefs) or [`reasons`](https://github.com/benthomasson/reasons) — belief registry management
- `claude` or `gemini` — at least one LLM CLI

Platform CLIs (install whichever you need):

- [`gh`](https://cli.github.com) — GitHub CLI
- [`glab`](https://gitlab.com/gitlab-org/cli) — GitLab CLI
- For Jira: set `JIRA_URL`, `JIRA_USER`, `JIRA_TOKEN` env vars

## Quick Start

```bash
# 1. Point project-expert at an issue tracker
project-expert init github owner/repo --domain "Payment platform"

# 2. Scan issues for an overview
project-expert scan

# 3. Explore topics one at a time
project-expert explore              # next topic
project-expert explore --pick 3     # specific topic
project-expert explore --pick 1,3,8 # multiple (stable indices)
project-expert explore --skip       # skip and move on

# 4. Extract beliefs from exploration entries
project-expert propose-beliefs
# Review proposed-beliefs.md — mark entries ACCEPT or REJECT
project-expert accept-beliefs

# 5. Check progress
project-expert status
```

## How It Works

project-expert follows a **scan → explore → distill → reason** pipeline:

```
scan              Fetch issues → LLM analysis → topic queue
  │
  ▼
explore           Pop one topic, fetch full issue, analyze deeply
  │                 ├── issue      Single issue deep-dive
  │                 ├── epic       Epic with children/blockers
  │                 ├── milestone  Milestone risk assessment
  │                 └── general    Cross-cutting analysis
  │
  ▼
propose-beliefs   Batch-extract factual claims from entries
  │
  ▼
accept-beliefs    Import reviewed claims into beliefs.md / reasons.db
```

Each exploration creates a dated entry in `entries/` and may generate new topics, so the queue grows organically as you learn.

## Supported Platforms

| Platform | Init Command | CLI Required |
|----------|-------------|-------------|
| GitHub | `project-expert init github owner/repo` | `gh` |
| GitLab | `project-expert init gitlab group/project` | `glab` |
| Jira | `project-expert init jira PROJ --jira-url URL` | None (REST API) |

## Commands

### `project-expert init <platform> <target>`

Bootstrap a knowledge base. Creates `.project-expert/` config, `entries/`, and belief store.

```bash
project-expert init github owner/repo --domain "Payment platform"
project-expert init gitlab group/project --domain "CI/CD infrastructure"
project-expert init jira MYPROJ --jira-url https://myco.atlassian.net
```

### `project-expert scan`

Fetch issues and produce an LLM-powered overview. Populates the topic queue with issues, epics, and milestones worth exploring.

```bash
project-expert scan
project-expert scan --limit 200           # fetch more issues
project-expert scan --labels bug,critical # filter by labels
project-expert scan --state closed        # scan closed issues
project-expert scan --jql "project=X AND priority=High"  # Jira JQL
```

### `project-expert explore`

Process the next topic in the queue. Fetches the full issue (with comments), runs deep analysis, creates an entry, and discovers follow-up topics.

```bash
project-expert explore              # next pending topic
project-expert explore --pick 2     # pick topic #2
project-expert explore --pick 1,3,8 # pick multiple (indices resolved before any are consumed)
project-expert explore --skip       # skip current topic
project-expert explore --loop 10    # continuously explore up to 10 topics
```

### `project-expert topics`

View the exploration queue.

```bash
project-expert topics       # pending only
project-expert topics --all # include done and skipped
```

### `project-expert propose-beliefs`

Extract candidate beliefs from exploration entries.

```bash
project-expert propose-beliefs
project-expert propose-beliefs --batch-size 10
```

Output goes to `proposed-beliefs.md`. Each proposal is marked `[ACCEPT]` or `[REJECT]` — review and flip as needed, then import.

### `project-expert accept-beliefs`

Import accepted proposals into `beliefs.md` or `reasons.db`.

```bash
project-expert accept-beliefs
project-expert accept-beliefs --file my-proposals.md
```

### `project-expert status`

Dashboard showing platform, entries, beliefs, topic queue, and cached issues.

## Global Options

| Option | Description |
|--------|-------------|
| `--model`, `-m` | Model to use: `claude` or `gemini` (default: claude) |
| `--quiet`, `-q` | Suppress explanation output to stdout |
| `--timeout`, `-t` | LLM timeout in seconds (default: 300) |
| `--version` | Show version |

## Project Layout

After `init`, the working directory gets:

```
.project-expert/
├── config.json           # platform, repo/project, domain
├── topics.json           # exploration queue
└── issues-cache.json     # cached issue data from last scan

entries/                   # dated exploration entries
├── 2026/04/09/
│   ├── scan-owner-repo.md
│   └── explore-GH-42.md

beliefs.md                # belief registry
proposed-beliefs.md       # proposals awaiting review
```

## Supported Models

| Name | CLI Command | Notes |
|------|-------------|-------|
| `claude` | `claude -p` | Default. Requires [Claude Code](https://claude.com/claude-code) |
| `gemini` | `gemini -p ""` | Requires Gemini CLI |
