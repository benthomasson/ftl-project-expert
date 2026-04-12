"""Scan prompt — overview of project issues."""

from .common import BELIEFS_INSTRUCTIONS, TOPICS_INSTRUCTIONS


def build_scan_prompt(
    issues_text: str,
    project_name: str,
    platform: str,
    issue_count: int,
    state: str | None = None,
    prs_text: str = "",
    pr_count: int = 0,
) -> str:
    """Build a prompt for scanning project issues and pull requests."""
    state_label = state or "open"
    if state_label in ("closed", "all"):
        state_instructions = _CLOSED_INSTRUCTIONS if state_label == "closed" else _ALL_INSTRUCTIONS
    else:
        state_instructions = _OPEN_INSTRUCTIONS

    prs_section = ""
    if prs_text:
        prs_section = f"""## Pull Requests ({pr_count} {state_label})

{prs_text}

"""

    pr_instructions = ""
    if pr_count > 0:
        pr_instructions = _PR_INSTRUCTIONS

    return f"""You are a senior project manager analyzing a project's issue tracker and pull requests.

## Project: {project_name}
## Platform: {platform}
## Issue state filter: {state_label}
## Total issues scanned: {issue_count}
## Total pull requests scanned: {pr_count}

## Issues

{issues_text}

{prs_section}## Instructions

{state_instructions}

{pr_instructions}

Be specific — reference issue IDs, PR numbers, assignees, and labels.

{TOPICS_INSTRUCTIONS}

{BELIEFS_INSTRUCTIONS}
"""


_OPEN_INSTRUCTIONS = """\
Analyze these **open** issues and provide:

1. **Project Overview** — What is this project about, based on the issues?
2. **Current State** — What's actively being worked on? What's blocked?
3. **Risk Areas** — Where are the bottlenecks, stale issues, or under-resourced areas?
4. **Milestone/Release Status** — Are any milestones at risk?
5. **Team Distribution** — Who's overloaded? Who has capacity?
6. **Patterns** — Common themes across issues (recurring bugs, feature areas, tech debt)"""

_CLOSED_INSTRUCTIONS = """\
Analyze these **closed/resolved** issues and provide:

1. **Project Overview** — What is this project about, based on the resolved work?
2. **Delivery Velocity** — How quickly are issues being resolved? What's the typical cycle time?
3. **Completed Work** — What features, fixes, and improvements have shipped?
4. **Team Contributions** — Who is delivering? How is work distributed across the team?
5. **Resolution Quality** — Are issues being closed with MRs? Are they well-tested? Any re-opened issues?
6. **Positive Patterns** — What's working well? Effective processes, strong areas, good collaboration signals?"""

_PR_INSTRUCTIONS = """\
Additionally, analyze the pull requests alongside the issues:

7. **Issue-PR Linkage** — Which issues have corresponding PRs? Which PRs close/fix which issues? Are there orphaned issues (no PR) or orphaned PRs (no linked issue)?
8. **Test Coverage** — Which PRs include test files? Are tests proportional to the changes? Flag PRs that modify source code without adding/updating tests.
9. **Review Quality** — Are PRs being reviewed? What feedback patterns appear in reviews? Are reviews substantive or rubber-stamps?
10. **Resolution Verification** — For closed issues, does the linked PR's diff actually address the issue described? Flag any issues closed without a corresponding code change."""

_ALL_INSTRUCTIONS = """\
Analyze these issues (both open and closed) and provide:

1. **Project Overview** — What is this project about?
2. **Health Ratio** — What fraction of issues are resolved vs open? Is the backlog growing or shrinking?
3. **Delivery Velocity** — How quickly are issues being resolved? Is velocity increasing or decreasing?
4. **Current State** — What's actively being worked on? What's blocked?
5. **Risk Areas** — Where are the bottlenecks, stale issues, or under-resourced areas?
6. **Strengths** — What's working well? Where is the team effective?
7. **Team Distribution** — Who's delivering? Who's overloaded? Who has capacity?
8. **Patterns** — Common themes across both resolved and open issues"""
