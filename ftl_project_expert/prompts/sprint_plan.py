"""Sprint plan prompt — generate prioritized sprint backlog from beliefs and issues."""


def build_sprint_plan_prompt(
    project_name: str,
    sprint_length: str,
    team_size: int,
    gating_section: str,
    team_section: str,
    backlog_section: str,
    beliefs_section: str,
    start_date: str = "",
) -> str:
    date_line = f"\n## Sprint start: {start_date}" if start_date else ""
    return f"""You are a senior engineering manager creating a sprint plan grounded in project data and a belief network.

## Project: {project_name}
## Sprint length: {sprint_length}
## Team size: {team_size}{date_line}

## Gated Items (blocking the most downstream work)

{gating_section}

## Team Capacity Signals

{team_section}

## Open Issues (ranked by impact)

{backlog_section}

## Belief Network Context (top beliefs by impact)

{beliefs_section}

## Instructions

Generate a sprint plan with these sections:

1. **Sprint Goal** — A one-sentence sprint goal that captures the highest-impact theme.

2. **Prioritized Backlog** (5-8 items) — Ranked by downstream beliefs unblocked and practical impact.
   For each item:
   - Issue ID and title
   - Why it is prioritized (which beliefs or conclusions does resolving it unblock)
   - Estimated effort (S/M/L based on issue complexity signals)
   - Suggested assignee with justification (capacity, expertise, bus-factor)

3. **Assignment Recommendations** — Who should work on what and why.
   Reference specific capacity signals (open issue count, recent velocity, expertise areas).
   Flag bus-factor risks where one person owns too much.

4. **Escalation Flags** — Items needing human authority decisions:
   - Unassigned critical/high-priority items
   - Stale blockers (no activity in 30+ days)
   - Cross-team dependencies
   - Staffing or re-prioritization decisions
   Be specific about what decision is needed and who should make it.

5. **Risk Summary** — Top 3-5 risks for this sprint:
   - What could go wrong
   - Likelihood signal from the data
   - Mitigation suggestion

Be concrete — reference issue IDs, belief IDs, team member names, and specific data points from the sections above. Do not invent information not present in the data.
"""
