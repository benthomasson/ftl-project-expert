"""Research prompt — verify a belief against its source system."""

RESEARCH_PROMPT = """\
You are verifying a belief from a project knowledge base against current source system data.

## Belief Under Investigation

**ID:** {belief_id}
**Claim:** {belief_text}
**Status in network:** {belief_status}

## Source Entry

The belief was extracted from this exploration entry:

{source_entry}

## Current Issue/PR State

Live data fetched from the issue tracker:

{artifacts}

## Dependent Beliefs

These beliefs depend on the one under investigation. If the investigated belief \
is disputed or stale, these may also be affected:

{dependents}

## Instructions

Compare the belief claim against the current source data. Look for:

1. **State changes** — Does the belief reference something as open/blocking/unresolved \
that is now closed, merged, or resolved?
2. **Factual accuracy** — Are specific claims (assignees, timelines, PR references, \
comment content) consistent with the current data?
3. **Reference integrity** — Do linked PRs/commits/issues actually exist and match \
what the belief claims about them? (e.g., a PR attributed to one purpose may actually \
be a different change by a different author)
4. **Staleness** — Has significant activity occurred since the belief was extracted \
that changes its validity?

## Output Format

Start with a verdict line:

VERDICT: VERIFIED | STALE | DISPUTED | UNVERIFIABLE

Then provide:

### Evidence
Specific observations from the source data that support your verdict. \
Reference issue IDs, PR numbers, dates, and quotes.

### Discrepancies
Any mismatches between the belief claim and current reality. Be specific.

### Impact
If the belief is stale or disputed, which dependent beliefs are affected and how?

### Recommendations
What should happen next? Retract the belief? Update it? Investigate further?
"""
