"""Explore prompt — deep dive into a specific issue or topic."""

from .common import BELIEFS_INSTRUCTIONS, TOPICS_INSTRUCTIONS


def build_explore_prompt(
    issue_text: str,
    context_text: str | None = None,
    question: str | None = None,
) -> str:
    """Build a prompt for exploring a specific issue or topic.

    Args:
        issue_text: The main issue(s) formatted as prompt text
        context_text: Optional related issues for context
        question: Optional guiding question
    """
    sections = [
        "You are a senior project manager analyzing project issues in depth.",
        "",
    ]

    if question:
        sections.append(f"**Focus question:** {question}")
        sections.append("")

    sections.extend([
        "## Issue Details",
        "",
        issue_text,
        "",
    ])

    if context_text:
        sections.extend([
            "## Related Issues",
            "",
            context_text,
            "",
        ])

    sections.extend([
        "## Instructions",
        "",
        "Provide a thorough analysis:",
        "",
        "1. **Summary** — What is this issue/epic about?",
        "2. **Status Assessment** — Is it on track? What's blocking progress?",
        "3. **Dependencies** — What does this depend on? What depends on it?",
        "4. **Risk** — What could go wrong? What's the blast radius?",
        "5. **Recommendations** — What should happen next?",
        "",
        "Be specific — reference issue IDs, timelines, and assignees.",
        "",
        TOPICS_INSTRUCTIONS,
        BELIEFS_INSTRUCTIONS,
    ])

    return "\n".join(sections)
