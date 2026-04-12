"""Summary prompt — synthesize project state from beliefs."""


def build_summary_prompt(
    beliefs_text: str,
    project_name: str,
    belief_count: int,
) -> str:
    """Build a prompt for summarizing project state from beliefs."""
    return f"""You are a senior project manager synthesizing a comprehensive project summary from verified beliefs about a project.

## Project: {project_name}
## Beliefs analyzed: {belief_count}

## Beliefs

{beliefs_text}

## Instructions

Synthesize these beliefs into a single, authoritative project summary. This should be the document someone reads to understand the project's current state in 5 minutes.

1. **Project Overview** — What is this project? What does it do? Who uses it?
2. **Architecture** — Key components, integrations, and technology stack
3. **Current State** — What's actively being worked on? What's the overall health?
4. **Key Risks** — The top 3-5 risks, ordered by impact. Be specific about why each matters.
5. **Team & Ownership** — Who's doing what? Where are the gaps?
6. **Milestones & Deadlines** — Any visible milestones, their status, and risk level
7. **Patterns & Themes** — Cross-cutting concerns that appear across multiple beliefs
8. **Recommendations** — Top 3-5 actions the team should take, ordered by priority

Be concrete — reference issue IDs, team members, and specific beliefs. Avoid generic advice. If beliefs contradict each other, note the contradiction.
"""
