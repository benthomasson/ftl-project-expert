"""Command-line interface for project expert."""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import click

from .llm import check_model_available, invoke, invoke_sync
from .prompts import (
    PROPOSE_BELIEFS_PROJECT,
    build_explore_prompt,
    build_scan_prompt,
    build_summary_prompt,
)
from .sources import GitHubSource, GitLabSource, Issue, JiraSource
from .topics import (
    Topic,
    add_topics,
    load_queue,
    parse_topics_from_response,
    pending_count,
    pop_at,
    pop_multiple,
    pop_next,
    skip_topic,
)

PROJECT_DIR = ".project-expert"


# --- Config helpers ---


def _load_config() -> dict | None:
    config_path = Path.cwd() / PROJECT_DIR / "config.json"
    if config_path.is_file():
        return json.loads(config_path.read_text())
    return None


def _save_config(config: dict) -> None:
    config_dir = Path.cwd() / PROJECT_DIR
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.json").write_text(json.dumps(config, indent=2))


def _get_project_dir() -> str:
    return str(Path.cwd() / PROJECT_DIR)


# --- Source helpers ---


def _get_source(config: dict) -> GitHubSource | GitLabSource | JiraSource:
    """Create the appropriate source from config."""
    platform = config["platform"]
    if platform == "github":
        return GitHubSource(config["repo"])
    elif platform == "gitlab":
        return GitLabSource(config["repo"])
    elif platform == "jira":
        return JiraSource(
            config["project"],
            url=config.get("jira_url"),
        )
    else:
        raise ValueError(f"Unknown platform: {platform}")


# --- Output helpers ---


def _emit(ctx, text: str) -> None:
    if not ctx.obj.get("quiet"):
        click.echo(text)


def _create_entry(topic: str, title: str, content: str) -> None:
    # Add HHMM timestamp so multiple scans on the same day don't collide
    timestamp = datetime.now().strftime("%H%M")
    entry_name = f"{topic}-{timestamp}"
    try:
        result = subprocess.run(
            ["entry", "create", entry_name, title, "--content", content],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            click.echo(f"Entry: {result.stdout.strip()}", err=True)
        else:
            result = subprocess.run(
                ["entry", "create", entry_name, title],
                input=content,
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                click.echo(f"Entry: {result.stdout.strip()}", err=True)
            else:
                click.echo(f"WARN: entry create failed: {result.stderr.strip()}", err=True)
    except FileNotFoundError:
        click.echo("WARN: entry CLI not found. Install with: uv tool install ftl-entry", err=True)


def _enqueue_topics(response: str, source: str, project_dir: str | None = None) -> None:
    new_topics = parse_topics_from_response(response, source=source)
    if new_topics:
        added = add_topics(new_topics, project_dir)
        if added:
            total = pending_count(project_dir)
            click.echo(f"Queued {added} new topic(s) ({total} pending)", err=True)


def _has_reasons() -> bool:
    return shutil.which("reasons") is not None


def _parse_beliefs_from_response(response: str) -> list[dict]:
    section_match = re.search(
        r"#+\s*Beliefs?\s*\n(.*?)(?=\n#|\Z)",
        response, re.DOTALL | re.IGNORECASE,
    )
    if not section_match:
        return []
    beliefs = []
    pattern = re.compile(r"^[-*]\s+`([^`]+)`\s*(?:—|-|:)\s*(.+)$", re.MULTILINE)
    for match in pattern.finditer(section_match.group(1)):
        beliefs.append({"id": match.group(1), "text": match.group(2).strip()})
    return beliefs


def _report_beliefs(response: str) -> None:
    beliefs = _parse_beliefs_from_response(response)
    if beliefs:
        click.echo(f"Surfaced {len(beliefs)} belief(s):", err=True)
        for b in beliefs[:5]:
            click.echo(f"  {b['id']}: {b['text'][:80]}", err=True)


def _reasons_export():
    beliefs_path = Path("beliefs.md")
    network_path = Path("network.json")
    result = subprocess.run(["reasons", "export-markdown"], capture_output=True, text=True)
    if result.returncode == 0:
        beliefs_path.write_text(result.stdout)
        click.echo(f"Updated {beliefs_path}")
    result = subprocess.run(["reasons", "export"], capture_output=True, text=True)
    if result.returncode == 0:
        network_path.write_text(result.stdout)
        click.echo(f"Updated {network_path}")


# --- CLI ---


@click.group()
@click.version_option(package_name="ftl-project-expert")
@click.option("--quiet", "-q", is_flag=True, default=False,
              help="Suppress output to stdout")
@click.option("--model", "-m", default="claude", help="Model to use (default: claude)")
@click.option("--timeout", "-t", default=300, type=int, help="LLM timeout in seconds")
@click.pass_context
def cli(ctx, quiet, model, timeout):
    """Build expert knowledge bases from project management data."""
    ctx.ensure_object(dict)
    ctx.obj["quiet"] = quiet
    ctx.obj["model"] = model
    ctx.obj["timeout"] = timeout


# --- init ---


@cli.command()
@click.argument("platform", type=click.Choice(["github", "gitlab", "jira"]))
@click.argument("target", type=str)
@click.option("--domain", "-d", default=None, help="One-line project description")
@click.option("--jira-url", default=None, help="Jira base URL (for jira platform)")
def init(platform, target, domain, jira_url):
    """Bootstrap a project-expert knowledge base.

    TARGET is owner/repo for GitHub/GitLab, or project key for Jira.

    Examples:
        project-expert init github owner/repo
        project-expert init gitlab group/project
        project-expert init jira MYPROJ --jira-url https://myco.atlassian.net
    """
    if not domain:
        domain = target

    # Check prerequisites
    for tool in ["entry"]:
        if not shutil.which(tool):
            click.echo(f"Error: {tool} not found on PATH", err=True)
            sys.exit(1)
    if not shutil.which("reasons") and not shutil.which("beliefs"):
        click.echo("Error: neither reasons nor beliefs found on PATH", err=True)
        sys.exit(1)

    # Check platform CLI
    if platform == "github" and not shutil.which("gh"):
        click.echo("Error: gh CLI not found. Install from https://cli.github.com", err=True)
        sys.exit(1)
    if platform == "gitlab" and not shutil.which("glab"):
        click.echo("Error: glab CLI not found.", err=True)
        sys.exit(1)
    if platform == "jira":
        if not jira_url and not os.environ.get("JIRA_URL"):
            click.echo("Error: --jira-url or JIRA_URL env var required for Jira", err=True)
            sys.exit(1)

    # Create project dir
    project_dir = Path.cwd() / PROJECT_DIR
    project_dir.mkdir(parents=True, exist_ok=True)

    # Save config
    config = {
        "platform": platform,
        "domain": domain,
        "created": date.today().isoformat(),
    }
    if platform in ("github", "gitlab"):
        config["repo"] = target
    else:
        config["project"] = target
        config["jira_url"] = jira_url or os.environ.get("JIRA_URL", "")

    _save_config(config)

    # Create entries dir
    Path("entries").mkdir(exist_ok=True)

    # Init belief store
    if _has_reasons():
        if not Path("reasons.db").exists():
            subprocess.run(["reasons", "init"], capture_output=True)
            click.echo("Initialized reasons.db")
        if not Path("beliefs.md").exists():
            _reasons_export()
    elif not Path("beliefs.md").exists():
        subprocess.run(["beliefs", "init"], capture_output=True)
        click.echo("Initialized beliefs.md")

    click.echo(f"\nInitialized project-expert")
    click.echo(f"  Platform: {platform}")
    click.echo(f"  Target:   {target}")
    click.echo(f"  Domain:   {domain}")
    click.echo(f"\nNext: project-expert scan")


# --- scan ---


@cli.command()
@click.option("--state", "-s", default=None,
              help="Issue state filter (default: open/opened)")
@click.option("--labels", "-l", default=None,
              help="Comma-separated labels to filter by")
@click.option("--limit", default=100, type=int,
              help="Max issues per page (default: 100)")
@click.option("--page", default=1, type=int,
              help="Page number for pagination (default: 1)")
@click.option("--all-pages", is_flag=True, default=False,
              help="Auto-paginate through all issues (uses --limit as page size)")
@click.option("--jql", default=None,
              help="Custom JQL query (Jira only)")
@click.pass_context
def scan(ctx, state, labels, limit, page, all_pages, jql):
    """Scan project issues and create an overview."""
    config = _load_config()
    if not config:
        click.echo("Not initialized. Run: project-expert init <platform> <target>")
        sys.exit(1)

    model = ctx.obj["model"]
    timeout = ctx.obj["timeout"]
    project_dir = _get_project_dir()

    if not check_model_available(model):
        click.echo(f"Error: Model '{model}' CLI not available", err=True)
        sys.exit(1)

    source = _get_source(config)
    label_list = [l.strip() for l in labels.split(",") if l.strip()] if labels else None

    # Set default state per platform
    if state is None:
        if config["platform"] == "gitlab":
            state = "opened"
        elif config["platform"] == "jira":
            state = "open"  # maps to statusCategory != "Done" in JQL
        else:
            state = "open"

    if all_pages:
        current_page = 1
        total_scanned = 0
        while True:
            click.echo(f"\n{'=' * 40}", err=True)
            click.echo(f"Page {current_page}", err=True)
            click.echo(f"{'=' * 40}", err=True)
            count = _scan_page(
                ctx, config, source, model, timeout, project_dir,
                state, label_list, limit, current_page, jql,
            )
            if count == 0:
                if total_scanned == 0:
                    click.echo("No issues found.")
                else:
                    click.echo(f"\nDone. Scanned {total_scanned} issues across {current_page - 1} pages.", err=True)
                break
            total_scanned += count
            if count < limit:
                click.echo(f"\nDone. Scanned {total_scanned} issues across {current_page} pages.", err=True)
                break
            current_page += 1
    else:
        _scan_page(
            ctx, config, source, model, timeout, project_dir,
            state, label_list, limit, page, jql,
        )


def _scan_page(ctx, config, source, model, timeout, project_dir,
               state, label_list, limit, page, jql):
    """Scan a single page of issues. Returns the number of issues fetched."""
    project_name = config.get("repo", config.get("project", "unknown"))
    click.echo(f"Scanning {project_name} (page {page})...", err=True)

    try:
        if config["platform"] == "jira":
            issues = source.list_issues(jql=jql, state=state, labels=label_list, limit=limit, page=page)
        elif config["platform"] == "gitlab":
            issues = source.list_issues(state=state, labels=label_list, limit=limit, page=page)
        else:
            issues = source.list_issues(state=state, labels=label_list, limit=limit)
    except Exception as e:
        click.echo(f"Error fetching issues: {e}", err=True)
        sys.exit(1)

    if not issues:
        return 0

    click.echo(f"Fetched {len(issues)} issues", err=True)

    # Fetch PRs for platforms that support them
    prs = []
    if config["platform"] in ("github", "gitlab") and hasattr(source, "list_prs"):
        try:
            prs = source.list_prs(state=state or "open", limit=limit)
            if prs:
                click.echo(f"Fetched {len(prs)} pull requests", err=True)
        except Exception as e:
            click.echo(f"Warning: Could not fetch PRs: {e}", err=True)

    # Build prompt
    issues_text = "\n\n".join(issue.to_prompt_text() for issue in issues)
    prs_text = ""
    if prs:
        prs_text = "\n\n".join(pr.to_prompt_text() for pr in prs)

    prompt = build_scan_prompt(
        issues_text=issues_text,
        prs_text=prs_text,
        project_name=project_name,
        platform=config["platform"],
        issue_count=len(issues),
        pr_count=len(prs),
        state=state,
    )

    click.echo(f"Running {model}...", err=True)
    try:
        result = asyncio.run(invoke(prompt, model, timeout=timeout))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Strip URL prefix for entry naming
    short_name = project_name.split("//")[-1] if "//" in project_name else project_name
    safe_name = short_name.replace("/", "-")
    state_suffix = f"-{state}" if state and state not in ("open", "opened") else ""
    page_suffix = f"-p{page}" if page > 1 else ""
    _create_entry(f"scan-{safe_name}{state_suffix}{page_suffix}", f"Scan: {project_name} ({state or 'open'}, page {page})", result)
    _enqueue_topics(result, source=f"scan:{project_name}", project_dir=project_dir)
    _report_beliefs(result)

    # Cache issues for explore
    _cache_issues(issues, project_dir)

    _emit(ctx, result)
    return len(issues)


def _cache_issues(issues: list[Issue], project_dir: str) -> None:
    """Cache fetched issues so explore can reference them without re-fetching."""
    cache_path = os.path.join(project_dir, "issues-cache.json")
    data = {}
    for issue in issues:
        data[issue.id] = {
            "id": issue.id,
            "title": issue.title,
            "url": issue.url,
            "platform": issue.platform,
            "body": issue.body,
            "state": issue.state,
            "labels": issue.labels,
            "assignees": issue.assignees,
            "milestone": issue.milestone,
            "priority": issue.priority,
            "issue_type": issue.issue_type,
            "parent": issue.parent,
            "children": issue.children,
            "linked": issue.linked,
            "author": issue.author,
            "created": issue.created,
            "updated": issue.updated,
            "comment_count": issue.comment_count,
        }
    os.makedirs(project_dir, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(data, f, indent=2)


def _load_cached_issues(project_dir: str) -> dict:
    """Load cached issues."""
    cache_path = os.path.join(project_dir, "issues-cache.json")
    if not os.path.isfile(cache_path):
        return {}
    with open(cache_path) as f:
        return json.load(f)


# --- topics ---


@cli.command()
@click.option("--all", "show_all", is_flag=True, default=False,
              help="Show all topics including done and skipped")
def topics(show_all):
    """Show the exploration queue."""
    queue = load_queue(_get_project_dir())

    if not queue:
        click.echo("No topics queued. Run `project-expert scan` to discover topics.")
        return

    pending = [t for t in queue if t.status == "pending"]
    done = [t for t in queue if t.status == "done"]
    skipped = [t for t in queue if t.status == "skipped"]

    if pending:
        click.echo(f"Pending ({len(pending)}):\n")
        for i, topic in enumerate(pending):
            click.echo(f"  {i}. [{topic.kind}] {topic.target}")
            click.echo(f"     {topic.title}")
            if topic.source:
                click.echo(f"     (from {topic.source})")
            click.echo()
    else:
        click.echo("No pending topics.")

    if show_all:
        if done:
            click.echo(f"Done ({len(done)}):\n")
            for topic in done:
                click.echo(f"  [{topic.kind}] {topic.target} - {topic.title}")
        if skipped:
            click.echo(f"\nSkipped ({len(skipped)}):\n")
            for topic in skipped:
                click.echo(f"  [{topic.kind}] {topic.target} - {topic.title}")

    click.echo(f"\n{len(pending)} pending, {len(done)} done, {len(skipped)} skipped")


# --- explore ---


@cli.command()
@click.option("--skip", "do_skip", is_flag=True, default=False,
              help="Skip the next topic")
@click.option("--pick", "pick_index", type=str, default=None,
              help="Pick topic(s) by index — single (3) or comma-separated (1,3,8)")
@click.option("--loop", "loop_max", type=int, default=None,
              help="Continuously explore up to N topics")
@click.pass_context
def explore(ctx, do_skip, pick_index, loop_max):
    """Explore the next topic in the queue."""
    project_dir = _get_project_dir()

    if loop_max is not None:
        if do_skip or pick_index:
            click.echo("Error: --loop cannot be combined with --skip or --pick", err=True)
            sys.exit(1)
        _explore_loop(ctx, project_dir, loop_max)
        return

    if do_skip:
        if skip_topic(0, project_dir):
            queue = load_queue(project_dir)
            pending = [t for t in queue if t.status == "pending"]
            if pending:
                click.echo(f"Skipped. Next: [{pending[0].kind}] {pending[0].target}")
            else:
                click.echo("Skipped. No more pending topics.")
        else:
            click.echo("Nothing to skip.")
        return

    if pick_index is not None:
        try:
            indices = [int(x.strip()) for x in pick_index.split(",")]
        except ValueError:
            click.echo(f"Error: --pick must be integers, got: {pick_index}", err=True)
            sys.exit(1)
        if len(indices) > 1:
            topic_list = pop_multiple(indices, project_dir)
        else:
            topic_list = [pop_at(indices[0], project_dir)]
    else:
        topic_list = [pop_next(project_dir)]

    valid_topics = [(i, t) for i, t in zip(
        indices if pick_index is not None else [0],
        topic_list,
    ) if t is not None]

    if not valid_topics:
        click.echo("No pending topics. Run `project-expert scan` to discover topics.")
        return

    invalid_count = len(topic_list) - len(valid_topics)
    if invalid_count:
        click.echo(f"Warning: {invalid_count} index(es) out of bounds, skipped.", err=True)

    for seq, (idx, topic) in enumerate(valid_topics):
        if len(valid_topics) > 1:
            click.echo(f"\n{'=' * 40}", err=True)
            click.echo(f"[{seq + 1}/{len(valid_topics)}] Topic #{idx}", err=True)
            click.echo(f"{'=' * 40}", err=True)

        _run_topic(ctx, topic)

    remaining = pending_count(project_dir)
    if remaining:
        click.echo(f"\n{remaining} topic(s) remaining.", err=True)
    else:
        click.echo("\nNo more topics. Exploration complete.", err=True)


def _explore_loop(ctx, project_dir, max_topics):
    """Continuously explore topics up to max_topics."""
    explored = 0
    while explored < max_topics:
        topic = pop_next(project_dir)
        if topic is None:
            if explored == 0:
                click.echo("No pending topics. Run `project-expert scan` to discover topics.")
            else:
                click.echo(f"\nNo more topics after {explored} exploration(s).", err=True)
            return

        explored += 1
        remaining = pending_count(project_dir)
        click.echo(f"\n{'=' * 40}", err=True)
        click.echo(f"[{explored}/{max_topics}] ({remaining} remaining in queue)", err=True)
        click.echo(f"{'=' * 40}", err=True)

        _run_topic(ctx, topic)

    remaining = pending_count(project_dir)
    click.echo(f"\nExplored {explored} topic(s). {remaining} remaining.", err=True)


def _run_topic(ctx, topic: Topic):
    """Explore a single topic."""
    model = ctx.obj["model"]
    timeout = ctx.obj["timeout"]
    project_dir = _get_project_dir()
    config = _load_config()

    if not check_model_available(model):
        click.echo(f"Error: Model '{model}' CLI not available", err=True)
        sys.exit(1)

    click.echo(f"Topic: [{topic.kind}] {topic.target}", err=True)
    click.echo(f"  {topic.title}", err=True)
    click.echo(err=True)

    # Fetch issue details if it's an issue/epic topic
    issue_text = ""
    context_text = ""

    if topic.kind in ("issue", "epic") and config:
        try:
            source = _get_source(config)
            # Extract issue number/key from target
            issue_id = topic.target
            if config["platform"] == "github":
                # Target might be "GH-123" or just "123"
                num = re.search(r"\d+", issue_id)
                if num:
                    issue = source.get_issue(int(num.group()))
                    issue_text = issue.to_prompt_text()

                    # Get related issues from cache
                    cached = _load_cached_issues(project_dir)
                    related_ids = issue.children + issue.linked
                    if issue.parent:
                        related_ids.append(issue.parent)
                    context_parts = []
                    for rid in related_ids:
                        if rid in cached:
                            ci = cached[rid]
                            context_parts.append(
                                f"### {ci['id']}: {ci['title']}\n"
                                f"- State: {ci['state']}\n"
                                f"- Labels: {', '.join(ci.get('labels', []))}"
                            )
                    if context_parts:
                        context_text = "\n\n".join(context_parts)

            elif config["platform"] == "gitlab":
                num = re.search(r"\d+", issue_id)
                if num:
                    issue = source.get_issue(int(num.group()))
                    issue_text = issue.to_prompt_text()

            elif config["platform"] == "jira":
                issue = source.get_issue(issue_id)
                issue_text = issue.to_prompt_text()

        except Exception as e:
            click.echo(f"Warning: Could not fetch issue {topic.target}: {e}", err=True)

    # If we couldn't fetch, use cached data or the title as context
    if not issue_text:
        cached = _load_cached_issues(project_dir)
        if topic.target in cached:
            ci = cached[topic.target]
            issue_text = (
                f"## {ci['id']}: {ci['title']}\n"
                f"- State: {ci['state']}\n"
                f"- Labels: {', '.join(ci.get('labels', []))}\n"
                f"- Assignees: {', '.join(ci.get('assignees', []))}\n"
            )
            if ci.get("body"):
                issue_text += f"\n### Description\n\n{ci['body']}"
        else:
            issue_text = f"## {topic.target}\n\n{topic.title}"

    prompt = build_explore_prompt(
        issue_text=issue_text,
        context_text=context_text or None,
        question=topic.title,
    )

    click.echo(f"Exploring with {model}...", err=True)
    try:
        result = asyncio.run(invoke(prompt, model, timeout=timeout))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return

    safe_target = re.sub(r"[^a-zA-Z0-9_-]", "-", topic.target)[:80]
    _create_entry(f"explore-{safe_target}", f"Explore: {topic.target}", result)
    _enqueue_topics(result, source=f"explore:{topic.target}", project_dir=project_dir)
    _report_beliefs(result)

    _emit(ctx, result)


# --- propose-beliefs ---


def _auto_accept_proposals(proposals: list[str]) -> None:
    """Parse LLM proposals and accept all beliefs directly."""
    accept_pattern = re.compile(
        r"### \[?(?:ACCEPT(?:/REJECT)?|REJECT)\]?\s*(\S+)\n"
        r"(.+?)\n"
        r"- Source: (.+?)(?:\n|$)",
        re.MULTILINE,
    )
    matches = []
    for proposal in proposals:
        matches.extend(accept_pattern.findall(proposal))

    if not matches:
        click.echo("No beliefs extracted from proposals.")
        return

    click.echo(f"Auto-accepting {len(matches)} beliefs...", err=True)

    if _has_reasons():
        added = 0
        for belief_id, claim_text, source in matches:
            result = subprocess.run(
                ["reasons", "add", belief_id, claim_text.strip(),
                 "--source", source.strip()],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                click.echo(f"  Added: {belief_id}", err=True)
                added += 1
            else:
                stderr = result.stderr.strip()
                stdout = result.stdout.strip()
                if "already exists" in stderr or "already exists" in stdout:
                    click.echo(f"  EXISTS: {belief_id}", err=True)
                else:
                    click.echo(f"  FAIL: {belief_id}: {stderr or stdout}", err=True)
        if added > 0:
            _reasons_export()
        click.echo(f"Accepted {added} belief(s).", err=True)
        return

    added = 0
    for belief_id, claim_text, source in matches:
        try:
            result = subprocess.run(
                ["beliefs", "add", "--id", belief_id,
                 "--text", claim_text.strip(), "--source", source.strip()],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                click.echo(f"  Added: {belief_id}", err=True)
                added += 1
            else:
                click.echo(f"  FAIL: {belief_id}: {result.stderr.strip()}", err=True)
        except FileNotFoundError:
            click.echo("ERROR: beliefs CLI not found.", err=True)
            return
    click.echo(f"Accepted {added} belief(s).", err=True)


def _entry_date(path: Path) -> str | None:
    """Extract YYYY-MM-DD date from an entry path like entries/2026/04/30/foo.md."""
    parts = path.parts
    for i, part in enumerate(parts):
        if part == "entries" and i + 3 < len(parts):
            try:
                y, m, d = parts[i + 1], parts[i + 2], parts[i + 3]
                if len(y) == 4 and len(m) == 2 and len(d) == 2:
                    return f"{y}-{m}-{d}"
            except (IndexError, ValueError):
                pass
    return None


@cli.command("propose-beliefs")
@click.option("--batch-size", type=int, default=5, help="Entries per LLM batch")
@click.option("--output", default="proposed-beliefs.md", help="Output file")
@click.option("--all", "process_all", is_flag=True, help="Re-process all entries")
@click.option("--auto", "auto_accept", is_flag=True, default=False,
              help="Automatically accept all proposed beliefs (no review step)")
@click.option("--since", default=None,
              help="Only process entries from this date onward (YYYY-MM-DD)")
@click.pass_context
def propose_beliefs(ctx, batch_size, output, process_all, auto_accept, since):
    """Extract candidate beliefs from entries for human review."""
    model = ctx.obj["model"]
    timeout = ctx.obj["timeout"]

    if not check_model_available(model):
        click.echo(f"Error: Model '{model}' CLI not available", err=True)
        sys.exit(1)

    input_dir = Path("entries")
    if not input_dir.exists():
        click.echo("No entries/ directory found. Run explorations first.")
        sys.exit(1)

    entries = sorted(input_dir.rglob("*.md"))
    if not entries:
        click.echo("No .md files found.")
        return

    if since:
        before = len(entries)
        entries = [e for e in entries if (_entry_date(e) or "") >= since]
        click.echo(f"Filtered to {len(entries)} entries since {since} (from {before} total)", err=True)
        if not entries:
            click.echo("No entries found since that date.")
            return

    click.echo(f"Reading {len(entries)} entries...")

    # Batch entries
    batches = []
    current_batch = []
    for entry_path in entries:
        content = entry_path.read_text()
        if len(content) > 10000:
            content = content[:10000] + "\n[Truncated]"
        current_batch.append(f"--- FILE: {entry_path} ---\n{content}")
        if len(current_batch) >= batch_size:
            batches.append("\n\n".join(current_batch))
            current_batch = []
    if current_batch:
        batches.append("\n\n".join(current_batch))

    click.echo(f"Processing {len(batches)} batches...")

    all_proposals = []
    for i, batch_text in enumerate(batches):
        click.echo(f"  Batch {i + 1}/{len(batches)}...")
        prompt = PROPOSE_BELIEFS_PROJECT.format(entries=batch_text)
        try:
            result = invoke_sync(prompt, model=model, timeout=timeout)
            all_proposals.append(result)
        except Exception as e:
            click.echo(f"  ERROR: {e}")
            continue

    if auto_accept:
        _auto_accept_proposals(all_proposals)
        return

    # Write proposals
    output_path = Path(output)
    with output_path.open("w") as f:
        f.write("# Proposed Beliefs\n\n")
        f.write("Edit each entry: change `[ACCEPT/REJECT]` to `[ACCEPT]` or `[REJECT]`.\n")
        f.write("Then run: `project-expert accept-beliefs`\n\n---\n\n")
        f.write(f"**Generated:** {date.today().isoformat()}\n")
        f.write(f"**Model:** {model}\n\n")
        for proposal in all_proposals:
            f.write(proposal)
            f.write("\n\n")

    click.echo(f"\nWrote {output_path}")
    click.echo("Review the file, then run: project-expert accept-beliefs")


# --- accept-beliefs ---


@cli.command("accept-beliefs")
@click.option("--file", "proposals_file", default="proposed-beliefs.md",
              help="Proposals file")
def accept_beliefs(proposals_file):
    """Import accepted beliefs from proposals file."""
    proposals_path = Path(proposals_file)
    if not proposals_path.exists():
        click.echo(f"Proposals file not found: {proposals_file}")
        sys.exit(1)

    text = proposals_path.read_text()

    pattern = re.compile(
        r"### \[?ACCEPT\]? (\S+)\n"
        r"(.+?)\n"
        r"- Source: (.+?)(?:\n|$)"
    )
    matches = pattern.findall(text)

    if not matches:
        click.echo("No [ACCEPT] entries found.")
        return

    click.echo(f"Found {len(matches)} accepted beliefs")

    if _has_reasons():
        added = 0
        for belief_id, claim_text, source in matches:
            result = subprocess.run(
                ["reasons", "add", belief_id, claim_text.strip(),
                 "--source", source.strip()],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                click.echo(f"  Added: {belief_id}")
                added += 1
            else:
                stderr = result.stderr.strip()
                stdout = result.stdout.strip()
                if "already exists" in stderr or "already exists" in stdout:
                    click.echo(f"  EXISTS: {belief_id}")
                else:
                    click.echo(f"  FAIL: {belief_id}: {stderr or stdout}")

        if added > 0:
            _reasons_export()
        return

    # Fall back to beliefs CLI
    added = 0
    for belief_id, claim_text, source in matches:
        try:
            result = subprocess.run(
                ["beliefs", "add", "--id", belief_id,
                 "--text", claim_text.strip(), "--source", source.strip()],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                click.echo(f"  Added: {belief_id}")
                added += 1
            else:
                click.echo(f"  FAIL: {belief_id}: {result.stderr.strip()}")
        except FileNotFoundError:
            click.echo("ERROR: beliefs CLI not found.")
            sys.exit(1)

    click.echo(f"\nAccepted {added} beliefs")


# --- review-proposals ---


_ISSUE_ID_PATTERN = re.compile(r"\b(GH-\d+|GL-\d+|MR-\d+|PR-\d+|[A-Z][A-Z0-9]+-\d+)\b")

_OPEN_WORDS = re.compile(
    r"\b(is open|remains open|still open|unresolved|is blocking|blocks|"
    r"is the sole blocker|open blocker|preventing completion|not yet resolved|"
    r"has no assignee|unassigned and open)\b",
    re.IGNORECASE,
)

_META_PATTERNS = re.compile(
    r"\b(belief network|belief graph|node count|nodes in the|cascade analysis|"
    r"retraction cascade|compaction|reason maintenance|knowledge base has|"
    r"belief registry|network growth|navigation feature|belief system)\b",
    re.IGNORECASE,
)

_EPHEMERAL_PATTERNS = re.compile(
    r"\b(as of \d{4}|currently \d+ (days?|weeks?|months?)|"
    r"has been open for \d+|open for \d+ days|"
    r"\d+ nodes as of|network has \d+ (nodes?|beliefs?))\b",
    re.IGNORECASE,
)

_SPECULATIVE_PATTERNS = re.compile(
    r"\b(could lead to|might cause|may result in|should be|"
    r"risk of|estimated|would likely|potentially|"
    r"if not addressed|suggests that perhaps)\b",
    re.IGNORECASE,
)


def _review_proposal(
    belief_id: str,
    claim_text: str,
    cached_issues: dict,
    existing_nodes: dict,
) -> tuple[bool, str | None]:
    """Check a single proposal against rejection criteria.

    Returns (reject, reason) — reject=True means the proposal should be marked REJECT.
    """
    # 1. Stale — references issues as open when they're closed
    issue_refs = _ISSUE_ID_PATTERN.findall(claim_text)
    if issue_refs and _OPEN_WORDS.search(claim_text):
        for ref in issue_refs:
            cached = cached_issues.get(ref)
            if cached and cached.get("state") in ("closed", "done", "resolved", "merged"):
                return True, f"stale: {ref} is {cached['state']}"

    # 2. Meta — about the belief network itself
    if _META_PATTERNS.search(claim_text):
        return True, "meta: about belief network, not the project"

    # 3. Duplicate — belief ID already exists in network
    if belief_id in existing_nodes:
        return True, f"duplicate: {belief_id} already exists"

    # 4. Duplicate — high word overlap with existing belief text
    claim_words = set(claim_text.lower().split())
    if len(claim_words) >= 4:
        for node_id, node in existing_nodes.items():
            node_text = node.get("text", "")
            node_words = set(node_text.lower().split())
            if not node_words:
                continue
            overlap = len(claim_words & node_words)
            union = len(claim_words | node_words)
            if union > 0 and overlap / union > 0.7:
                return True, f"duplicate: overlaps with {node_id}"

    # 5. Ephemeral — time-bound snapshots
    if _EPHEMERAL_PATTERNS.search(claim_text):
        return True, "ephemeral: time-bound snapshot"

    # 6. Speculative — editorial/predictive language
    if _SPECULATIVE_PATTERNS.search(claim_text):
        return True, "speculative: predictive/editorial language"

    return False, None


@cli.command("review-proposals")
@click.option("--file", "proposals_file", default="proposed-beliefs.md",
              help="Proposals file to review")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show what would be rejected without modifying the file")
@click.pass_context
def review_proposals(ctx, proposals_file, dry_run):
    """Filter low-quality belief proposals before acceptance.

    Checks proposals against rejection criteria: stale issue references,
    meta/navel-gazing, duplicates, ephemeral snapshots, and speculative claims.

    Pipeline position: propose-beliefs → review-proposals → accept-beliefs
    """
    proposals_path = Path(proposals_file)
    if not proposals_path.exists():
        click.echo(f"Proposals file not found: {proposals_file}")
        sys.exit(1)

    project_dir = _get_project_dir()
    text = proposals_path.read_text()

    # Load context for checks
    cached_issues = _load_cached_issues(project_dir)
    try:
        network = _load_network()
        existing_nodes = network.get("nodes", {})
    except Exception:
        existing_nodes = {}

    # Parse all proposals
    proposal_pattern = re.compile(
        r"(### \[?(?:ACCEPT(?:/REJECT)?|REJECT)\]?)\s*(\S+)\n"
        r"(.+?)\n"
        r"(- Source: .+?)(?=\n###|\n---|\Z)",
        re.DOTALL,
    )

    matches = list(proposal_pattern.finditer(text))
    if not matches:
        click.echo("No proposals found in file.")
        return

    # Review each proposal
    kept = 0
    rejected = 0
    categories: dict[str, int] = {}
    replacements: list[tuple[str, str]] = []

    for match in matches:
        header = match.group(1)
        belief_id = match.group(2)
        claim_text = match.group(3).strip()

        # Skip already-rejected proposals
        if "[REJECT]" in header and "[ACCEPT" not in header:
            kept += 1
            continue

        reject, reason = _review_proposal(
            belief_id, claim_text, cached_issues, existing_nodes,
        )

        if reject:
            rejected += 1
            category = reason.split(":")[0] if reason else "unknown"
            categories[category] = categories.get(category, 0) + 1

            old_block = match.group(0)
            new_header = f"### [REJECT] {belief_id}"
            new_block = old_block.replace(
                f"{header} {belief_id}",
                f"{new_header}",
                1,
            )
            # Append reason after the source line
            source_line = match.group(4).strip()
            new_block = new_block.replace(
                source_line,
                f"{source_line}\n- Rejected: {reason}",
                1,
            )
            replacements.append((old_block, new_block))

            if dry_run:
                click.echo(f"  REJECT {belief_id}: {reason}", err=True)
        else:
            kept += 1

    # Summary
    click.echo(f"\nReviewed {len(matches)} proposals: {kept} kept, {rejected} rejected", err=True)
    if categories:
        click.echo("Rejections by category:", err=True)
        for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
            click.echo(f"  {cat}: {count}", err=True)

    if dry_run:
        click.echo("\nDry run — no changes written.", err=True)
        return

    # Apply replacements
    if replacements:
        for old_block, new_block in replacements:
            text = text.replace(old_block, new_block, 1)
        proposals_path.write_text(text)
        click.echo(f"Updated {proposals_file}", err=True)
    else:
        click.echo("No changes needed.", err=True)


# --- derive ---


def _load_network() -> dict:
    """Load network.json (exported from reasons)."""
    network_path = Path("network.json")
    if not network_path.exists():
        if _has_reasons():
            result = subprocess.run(
                ["reasons", "export"], capture_output=True, text=True,
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        return {"nodes": {}}
    return json.loads(network_path.read_text())


def _get_depth(node_id: str, nodes: dict, derived: dict, memo: dict | None = None) -> int:
    """Compute the depth of a node in the reasoning chain."""
    if memo is None:
        memo = {}
    if node_id in memo:
        return memo[node_id]
    if node_id not in derived:
        memo[node_id] = 0
        return 0
    max_d = 0
    for j in derived[node_id].get("justifications", []):
        for a in j.get("antecedents", []):
            max_d = max(max_d, _get_depth(a, nodes, derived, memo))
    memo[node_id] = max_d + 1
    return max_d + 1


def _build_beliefs_section(nodes: dict, derived: dict, max_beliefs: int = 300) -> str:
    """Build a compact beliefs section for the derive prompt."""
    from collections import defaultdict
    lines = []
    in_nodes = {k: v for k, v in nodes.items()
                if v.get("truth_value") == "IN" and k not in derived}
    groups = defaultdict(list)
    for k, v in in_nodes.items():
        prefix = k.split("-")[0] if "-" in k else k
        groups[prefix].append((k, v["text"][:120]))

    count = 0
    for prefix in sorted(groups, key=lambda p: -len(groups[p])):
        if count >= max_beliefs:
            break
        lines.append(f"\n### {prefix} ({len(groups[prefix])} beliefs)")
        for belief_id, text in sorted(groups[prefix]):
            if count >= max_beliefs:
                break
            lines.append(f"- `{belief_id}`: {text}")
            count += 1

    return "\n".join(lines)


def _build_derived_section(nodes: dict, derived: dict) -> str:
    """Build the derived conclusions section for the derive prompt."""
    memo = {}
    lines = []
    for k in sorted(derived, key=lambda x: -_get_depth(x, nodes, derived, memo)):
        depth = _get_depth(k, nodes, derived, memo)
        text = nodes[k]["text"][:150]
        justs = derived[k]["justifications"]
        antes = justs[0].get("antecedents", []) if justs else []
        outlist = justs[0].get("outlist", []) if justs else []
        status = nodes[k].get("truth_value", "?")

        lines.append(f"\n#### [{status}] depth-{depth}: `{k}`")
        lines.append(text)
        lines.append(f"- Antecedents: {', '.join(antes)}")
        if outlist:
            lines.append(f"- Unless: {', '.join(outlist)}")

    return "\n".join(lines) if lines else "(No derived conclusions yet)"


def _parse_derive_proposals(response: str) -> list[dict]:
    """Parse DERIVE and GATE proposals from LLM response."""
    proposals = []
    pattern = re.compile(
        r"### (DERIVE|GATE) (\S+)\n"
        r"(.+?)\n"
        r"- Antecedents: (.+?)\n"
        r"(?:- Unless: (.+?)\n)?"
        r"- Label: (.+?)(?:\n|$)",
    )
    for match in pattern.finditer(response):
        kind = match.group(1)
        proposal = {
            "kind": kind.lower(),
            "id": match.group(2).strip("`"),
            "text": match.group(3).strip(),
            "antecedents": [a.strip().strip("`") for a in match.group(4).split(",")],
            "unless": [u.strip().strip("`") for u in match.group(5).split(",")] if match.group(5) else [],
            "label": match.group(6).strip(),
        }
        proposals.append(proposal)
    return proposals


def _derive_once(model: str, timeout: int) -> int:
    """Run a single derivation round. Returns number of beliefs added."""
    from .prompts.derive import DERIVE_BELIEFS_PROMPT

    network = _load_network()
    nodes = network.get("nodes", {})
    if not nodes:
        return 0

    derived = {k: v for k, v in nodes.items()
               if v.get("justifications") and len(v["justifications"]) > 0}
    in_nodes = {k: v for k, v in nodes.items() if v.get("truth_value") == "IN"}
    memo = {}
    max_depth = max((_get_depth(k, nodes, derived, memo) for k in derived), default=0)

    click.echo(f"Network: {len(in_nodes)} IN, {len(derived)} derived, depth {max_depth}", err=True)

    beliefs_section = _build_beliefs_section(nodes, derived)
    derived_section = _build_derived_section(nodes, derived)

    prompt = DERIVE_BELIEFS_PROMPT.format(
        beliefs_section=beliefs_section,
        derived_section=derived_section,
        total_in=len(in_nodes),
        total_derived=len(derived),
        max_depth=max_depth,
    )

    click.echo(f"Deriving with {model}...", err=True)
    result = asyncio.run(invoke(prompt, model, timeout=timeout))

    proposals = _parse_derive_proposals(result)
    if not proposals:
        return 0

    valid = []
    for p in proposals:
        missing = [a for a in p["antecedents"] if a not in nodes]
        missing_unless = [u for u in p["unless"] if u not in nodes]
        if missing or missing_unless:
            click.echo(f"  SKIP {p['id']}: missing nodes {missing + missing_unless}", err=True)
            continue
        if p["id"] in nodes:
            click.echo(f"  SKIP {p['id']}: already exists", err=True)
            continue
        valid.append(p)

    if not valid:
        return 0

    added = 0
    for p in valid:
        cmd = [
            "reasons", "add", p["id"], p["text"],
            "--sl", ",".join(p["antecedents"]),
            "--label", p["label"],
        ]
        if p["unless"]:
            cmd.extend(["--unless", ",".join(p["unless"])])

        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            status = "IN" if "IN" in r.stdout else "OUT"
            click.echo(f"  Added {p['id']} [{status}]")
            added += 1
        else:
            click.echo(f"  FAIL {p['id']}: {r.stderr.strip() or r.stdout.strip()}", err=True)

    if added:
        _reasons_export()

    return added


@cli.command("derive")
@click.option("--output", "-o", default="proposed-derivations.md",
              help="Output file (default: proposed-derivations.md)")
@click.option("--auto", "auto_add", is_flag=True, default=False,
              help="Automatically add proposals to reasons (no review step)")
@click.option("--exhaust", "exhaust", is_flag=True, default=False,
              help="Loop until no new derivations (implies --auto)")
@click.option("--max-rounds", type=int, default=5,
              help="Max derivation rounds for --exhaust (default: 5)")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show what would be sent to the LLM without invoking it")
@click.pass_context
def derive(ctx, output, auto_add, exhaust, max_rounds, dry_run):
    """Derive deeper reasoning chains from existing beliefs.

    Analyzes the belief network for opportunities to combine existing
    conclusions into higher-level project claims, and to connect positive
    and negative chains via outlist semantics.

    Example:
        project-expert derive              # propose derivations
        project-expert derive --auto       # propose and add automatically
        project-expert derive --exhaust    # loop until convergence
    """
    from .prompts.derive import DERIVE_BELIEFS_PROMPT

    model = ctx.obj["model"]
    timeout = ctx.obj["timeout"]

    if not _has_reasons():
        click.echo("Error: reasons CLI required. Install with: uv tool install ftl-reasons", err=True)
        sys.exit(1)

    if not check_model_available(model):
        click.echo(f"Error: Model '{model}' CLI not available", err=True)
        sys.exit(1)

    if exhaust:
        total_added = 0
        for round_num in range(1, max_rounds + 1):
            click.echo(f"\n--- Derive round {round_num}/{max_rounds} ---", err=True)
            try:
                added = _derive_once(model, timeout)
            except Exception as e:
                click.echo(f"Error in round {round_num}: {e}", err=True)
                break
            total_added += added
            if added == 0:
                click.echo("No new derivations. Converged.", err=True)
                break
            click.echo(f"Round {round_num}: added {added} derivation(s).", err=True)
        click.echo(f"\nExhaust complete: {total_added} total derivation(s) across {round_num} round(s).", err=True)
        return

    # Single-round mode
    network = _load_network()
    nodes = network.get("nodes", {})
    if not nodes:
        click.echo("No beliefs found. Run explorations first.", err=True)
        sys.exit(1)

    derived = {k: v for k, v in nodes.items()
               if v.get("justifications") and len(v["justifications"]) > 0}
    in_nodes = {k: v for k, v in nodes.items() if v.get("truth_value") == "IN"}
    memo = {}
    max_depth = max((_get_depth(k, nodes, derived, memo) for k in derived), default=0)

    click.echo(f"Network: {len(in_nodes)} IN beliefs, {len(derived)} derived, max depth {max_depth}", err=True)

    beliefs_section = _build_beliefs_section(nodes, derived)
    derived_section = _build_derived_section(nodes, derived)

    prompt = DERIVE_BELIEFS_PROMPT.format(
        beliefs_section=beliefs_section,
        derived_section=derived_section,
        total_in=len(in_nodes),
        total_derived=len(derived),
        max_depth=max_depth,
    )

    if dry_run:
        click.echo(f"\n=== Prompt ({len(prompt)} chars) ===\n")
        click.echo(prompt[:3000])
        if len(prompt) > 3000:
            click.echo(f"\n... ({len(prompt) - 3000} more chars)")
        return

    click.echo(f"Deriving with {model}...", err=True)
    try:
        result = asyncio.run(invoke(prompt, model, timeout=timeout))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    proposals = _parse_derive_proposals(result)

    if not proposals:
        click.echo("No derivation proposals found in response.")
        click.echo("\nRaw response:\n")
        click.echo(result)
        return

    valid = []
    for p in proposals:
        missing = [a for a in p["antecedents"] if a not in nodes]
        missing_unless = [u for u in p["unless"] if u not in nodes]
        if missing or missing_unless:
            click.echo(f"  SKIP {p['id']}: missing nodes {missing + missing_unless}", err=True)
            continue
        if p["id"] in nodes:
            click.echo(f"  SKIP {p['id']}: already exists", err=True)
            continue
        valid.append(p)

    click.echo(f"\n{len(valid)} valid proposals ({len(proposals) - len(valid)} skipped)", err=True)

    if not valid:
        return

    if auto_add:
        added = 0
        for p in valid:
            cmd = [
                "reasons", "add", p["id"], p["text"],
                "--sl", ",".join(p["antecedents"]),
                "--label", p["label"],
            ]
            if p["unless"]:
                cmd.extend(["--unless", ",".join(p["unless"])])

            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0:
                status = "IN" if "IN" in r.stdout else "OUT"
                click.echo(f"  Added {p['id']} [{status}]")
                added += 1
            else:
                click.echo(f"  FAIL {p['id']}: {r.stderr.strip() or r.stdout.strip()}", err=True)

        if added:
            click.echo(f"\nAdded {added} derived beliefs.", err=True)
            _reasons_export()
        return

    # Write proposals file for review
    output_path = Path(output)
    with output_path.open("w") as f:
        f.write("# Proposed Derivations\n\n")
        f.write("Review each proposal below. To accept, run:\n\n")
        f.write("```bash\n")
        for p in valid:
            sl = ",".join(p["antecedents"])
            cmd = f'reasons add {p["id"]} "{p["text"]}" --sl {sl}'
            if p["unless"]:
                cmd += f' --unless {",".join(p["unless"])}'
            cmd += f' --label "{p["label"]}"'
            f.write(f"{cmd}\n")
        f.write("```\n\n---\n\n")

        for p in valid:
            kind_label = "DERIVE" if p["kind"] == "derive" else "GATE (outlist)"
            f.write(f"### {kind_label}: `{p['id']}`\n\n")
            f.write(f"{p['text']}\n\n")
            f.write(f"- **Antecedents**: {', '.join(f'`{a}`' for a in p['antecedents'])}\n")
            if p["unless"]:
                f.write(f"- **Unless**: {', '.join(f'`{u}`' for u in p['unless'])}\n")
            f.write(f"- **Label**: {p['label']}\n\n")

    click.echo(f"\nWrote {output_path} ({len(valid)} proposals)")
    click.echo("Review, then run the commands from the file to accept.")
    click.echo("Or re-run with --auto to add automatically.")


# --- summary ---


@cli.command()
@click.pass_context
def summary(ctx):
    """Synthesize a project summary from beliefs."""
    config = _load_config()
    if not config:
        click.echo("Not initialized. Run: project-expert init <platform> <target>")
        sys.exit(1)

    model = ctx.obj["model"]
    timeout = ctx.obj["timeout"]

    if not check_model_available(model):
        click.echo(f"Error: Model '{model}' CLI not available", err=True)
        sys.exit(1)

    # Read beliefs from reasons or beliefs.md
    beliefs_text = ""
    belief_count = 0

    if _has_reasons() and Path("reasons.db").exists():
        result = subprocess.run(["reasons", "list"], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            beliefs_text = result.stdout
            belief_count = len([l for l in result.stdout.splitlines() if l.strip()])
    elif Path("beliefs.md").exists():
        beliefs_text = Path("beliefs.md").read_text()
        belief_count = len(re.findall(r"^### \S+", beliefs_text, re.MULTILINE))

    if not beliefs_text or belief_count == 0:
        click.echo("No beliefs found. Run the pipeline first:")
        click.echo("  project-expert scan")
        click.echo("  project-expert propose-beliefs")
        click.echo("  project-expert accept-beliefs")
        sys.exit(1)

    click.echo(f"Summarizing {belief_count} beliefs with {model}...", err=True)

    project_name = config.get("repo", config.get("project", "unknown"))

    prompt = build_summary_prompt(
        beliefs_text=beliefs_text,
        project_name=project_name,
        belief_count=belief_count,
    )

    try:
        result = asyncio.run(invoke(prompt, model, timeout=timeout))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    short_name = project_name.split("//")[-1] if "//" in project_name else project_name
    safe_name = short_name.replace("/", "-")
    _create_entry(f"summary-{safe_name}", f"Summary: {project_name}", result)

    _emit(ctx, result)


# --- status ---


@cli.command()
def status():
    """Show project-expert dashboard."""
    config = _load_config()

    click.echo("=== Project Expert Status ===\n")

    if config:
        click.echo(f"Platform: {config.get('platform', 'unknown')}")
        click.echo(f"Target:   {config.get('repo', config.get('project', 'unknown'))}")
        click.echo(f"Domain:   {config.get('domain', 'unknown')}")
        click.echo(f"Created:  {config.get('created', 'unknown')}")
    else:
        click.echo("Not initialized. Run: project-expert init <platform> <target>")
        return

    click.echo()

    # Entries
    entries_dir = Path("entries")
    entry_count = len(list(entries_dir.rglob("*.md"))) if entries_dir.exists() else 0
    click.echo(f"Entries:  {entry_count}")

    # Beliefs
    if _has_reasons() and Path("reasons.db").exists():
        result = subprocess.run(["reasons", "list"], capture_output=True, text=True)
        if result.returncode == 0:
            lines = result.stdout.splitlines()
            r_in = sum(1 for l in lines if l.strip().startswith("[+]"))
            r_out = sum(1 for l in lines if l.strip().startswith("[-]"))
            click.echo(f"Beliefs:  {r_in} IN, {r_out} OUT")
    else:
        beliefs_path = Path("beliefs.md")
        if beliefs_path.exists():
            text = beliefs_path.read_text()
            b_in = len(re.findall(r"^### \S+ \[IN\]", text, re.MULTILINE))
            click.echo(f"Beliefs:  {b_in} IN")

    # Topics
    project_dir = _get_project_dir()
    queue = load_queue(project_dir)
    pending = sum(1 for t in queue if t.status == "pending")
    done = sum(1 for t in queue if t.status == "done")
    skipped = sum(1 for t in queue if t.status == "skipped")
    click.echo(f"Topics:   {pending} pending, {done} done, {skipped} skipped")

    # Cached issues
    cached = _load_cached_issues(project_dir)
    if cached:
        click.echo(f"Cached:   {len(cached)} issues")

    # Proposals
    proposals_path = Path("proposed-beliefs.md")
    if proposals_path.exists():
        text = proposals_path.read_text()
        total = len(re.findall(r"^### \[(?:ACCEPT|REJECT|ACCEPT/REJECT)\]", text, re.MULTILINE))
        accepted = len(re.findall(r"^### \[ACCEPT\]", text, re.MULTILINE))
        click.echo(f"Proposed: {total} candidates ({accepted} accepted)")


# --- update ---


def _save_update_checkpoint(project_dir: str) -> None:
    """Save current timestamp as the update checkpoint."""
    checkpoint = {
        "timestamp": datetime.now().isoformat(),
        "since": date.today().isoformat(),
    }
    checkpoint_path = os.path.join(project_dir, "last-update.json")
    os.makedirs(project_dir, exist_ok=True)
    with open(checkpoint_path, "w") as f:
        json.dump(checkpoint, f, indent=2)


def _load_update_checkpoint(project_dir: str) -> str | None:
    """Load the since date from the last update checkpoint."""
    checkpoint_path = os.path.join(project_dir, "last-update.json")
    if not os.path.isfile(checkpoint_path):
        return None
    with open(checkpoint_path) as f:
        data = json.load(f)
    return data.get("since")


@cli.command("update")
@click.option("--since", default=None,
              help="Fetch issues updated since date (YYYY-MM-DD)")
@click.option("--since-last", is_flag=True, default=False,
              help="Resume from last update checkpoint")
@click.option("--state", "-s", default=None,
              help="Issue state filter (default: all)")
@click.option("--limit", default=100, type=int,
              help="Max issues per page (default: 100)")
@click.option("--all-pages", is_flag=True, default=False,
              help="Auto-paginate through all matching issues")
@click.option("--max-explore", type=int, default=None,
              help="Max topics to explore (default: all pending)")
@click.pass_context
def update(ctx, since, since_last, state, limit, all_pages, max_explore):
    """Automated update pipeline: scan, explore, extract beliefs, derive, summarize.

    Pulls all issues/PRs updated since a date, explores them, proposes and
    accepts beliefs, derives logical consequences, and generates a summary.

    Examples:
        project-expert update --since 2026-04-01
        project-expert update --since-last
        project-expert update --since "2026-04-01" --all-pages
    """
    config = _load_config()
    if not config:
        click.echo("Not initialized. Run: project-expert init <platform> <target>")
        sys.exit(1)

    model = ctx.obj["model"]
    timeout = ctx.obj["timeout"]
    project_dir = _get_project_dir()

    if not check_model_available(model):
        click.echo(f"Error: Model '{model}' CLI not available", err=True)
        sys.exit(1)

    # Resolve since date
    if since_last:
        since = _load_update_checkpoint(project_dir)
        if not since:
            click.echo("No checkpoint found. Use --since <date> for the first run.", err=True)
            sys.exit(1)
        click.echo(f"Resuming from checkpoint: since {since}", err=True)
    elif not since:
        click.echo("Error: --since <date> or --since-last required.", err=True)
        sys.exit(1)

    # Default to "all" states for update (we want to see everything that changed)
    if state is None:
        state = "all"

    # Snapshot pre-run belief IDs
    try:
        network = _load_network()
        pre_run_ids = set(network.get("nodes", {}).keys())
    except Exception:
        pre_run_ids = set()

    errors = []
    project_name = config.get("repo", config.get("project", "unknown"))
    source = _get_source(config)

    # --- Step 1: Fetch and scan issues ---
    click.echo(f"\n{'=' * 40}", err=True)
    click.echo("Step 1: Scanning issues/PRs", err=True)
    click.echo(f"{'=' * 40}", err=True)

    try:
        label_list = None
        total_issues = 0

        if all_pages:
            current_page = 1
            while True:
                click.echo(f"  Fetching page {current_page}...", err=True)
                issues = _fetch_issues(source, config, state=state, labels=label_list,
                                       limit=limit, page=current_page, since=since)
                if not issues:
                    break
                total_issues += len(issues)
                _run_scan_step(ctx, config, source, issues, project_name,
                               state, limit, current_page, project_dir, model, timeout)
                if len(issues) < limit:
                    break
                current_page += 1
        else:
            issues = _fetch_issues(source, config, state=state, labels=label_list,
                                   limit=limit, page=1, since=since)
            if issues:
                total_issues = len(issues)
                _run_scan_step(ctx, config, source, issues, project_name,
                               state, limit, 1, project_dir, model, timeout)

        if total_issues == 0:
            click.echo("No issues found since {since}.", err=True)
        else:
            click.echo(f"Scanned {total_issues} issue(s).", err=True)

    except SystemExit as e:
        if e.code and e.code != 0:
            errors.append(f"scan exited with code {e.code}")
            click.echo(f"WARN: scan failed (exit {e.code}), continuing...", err=True)
    except Exception as e:
        errors.append(f"scan: {e}")
        click.echo(f"WARN: scan failed: {e}, continuing...", err=True)

    # --- Step 2: Explore all pending topics ---
    click.echo(f"\n{'=' * 40}", err=True)
    click.echo("Step 2: Exploring topics", err=True)
    click.echo(f"{'=' * 40}", err=True)

    try:
        topic_limit = max_explore or 99
        explored = 0
        while explored < topic_limit:
            topic = pop_next(project_dir)
            if topic is None:
                break
            explored += 1
            remaining = pending_count(project_dir)
            click.echo(f"\n  [{explored}] ({remaining} remaining)", err=True)
            _run_topic(ctx, topic)

        if explored == 0:
            click.echo("No topics to explore.", err=True)
        else:
            click.echo(f"Explored {explored} topic(s).", err=True)

    except SystemExit as e:
        if e.code and e.code != 0:
            errors.append(f"explore exited with code {e.code}")
            click.echo(f"WARN: explore failed (exit {e.code}), continuing...", err=True)
    except Exception as e:
        errors.append(f"explore: {e}")
        click.echo(f"WARN: explore failed: {e}, continuing...", err=True)

    # --- Step 3: Propose beliefs ---
    click.echo(f"\n{'=' * 40}", err=True)
    click.echo("Step 3: Proposing beliefs", err=True)
    click.echo(f"{'=' * 40}", err=True)

    try:
        ctx.invoke(propose_beliefs, since=since)
    except SystemExit as e:
        if e.code and e.code != 0:
            errors.append(f"propose-beliefs exited with code {e.code}")
            click.echo(f"WARN: propose-beliefs failed (exit {e.code}), continuing...", err=True)
    except Exception as e:
        errors.append(f"propose-beliefs: {e}")
        click.echo(f"WARN: propose-beliefs failed: {e}, continuing...", err=True)

    # --- Step 4: Review proposals ---
    click.echo(f"\n{'=' * 40}", err=True)
    click.echo("Step 4: Reviewing proposals", err=True)
    click.echo(f"{'=' * 40}", err=True)

    try:
        ctx.invoke(review_proposals)
    except SystemExit as e:
        if e.code and e.code != 0:
            errors.append(f"review-proposals exited with code {e.code}")
            click.echo(f"WARN: review-proposals failed (exit {e.code}), continuing...", err=True)
    except Exception as e:
        errors.append(f"review-proposals: {e}")
        click.echo(f"WARN: review-proposals failed: {e}, continuing...", err=True)

    # --- Step 5: Accept beliefs ---
    click.echo(f"\n{'=' * 40}", err=True)
    click.echo("Step 5: Accepting beliefs", err=True)
    click.echo(f"{'=' * 40}", err=True)

    try:
        ctx.invoke(accept_beliefs)
    except SystemExit as e:
        if e.code and e.code != 0:
            errors.append(f"accept-beliefs exited with code {e.code}")
            click.echo(f"WARN: accept-beliefs failed (exit {e.code}), continuing...", err=True)
    except Exception as e:
        errors.append(f"accept-beliefs: {e}")
        click.echo(f"WARN: accept-beliefs failed: {e}, continuing...", err=True)

    # --- Step 6: Derive (exhaust) ---
    click.echo(f"\n{'=' * 40}", err=True)
    click.echo("Step 6: Deriving logical consequences", err=True)
    click.echo(f"{'=' * 40}", err=True)

    try:
        ctx.invoke(derive, exhaust=True)
    except SystemExit as e:
        if e.code and e.code != 0:
            errors.append(f"derive exited with code {e.code}")
            click.echo(f"WARN: derive failed (exit {e.code}), continuing...", err=True)
    except Exception as e:
        errors.append(f"derive: {e}")
        click.echo(f"WARN: derive failed: {e}, continuing...", err=True)

    # --- Step 7: Summary ---
    click.echo(f"\n{'=' * 40}", err=True)
    click.echo("Step 7: Generating summary", err=True)
    click.echo(f"{'=' * 40}", err=True)

    try:
        ctx.invoke(summary)
    except SystemExit as e:
        if e.code and e.code != 0:
            errors.append(f"summary exited with code {e.code}")
            click.echo(f"WARN: summary failed (exit {e.code}), continuing...", err=True)
    except Exception as e:
        errors.append(f"summary: {e}")
        click.echo(f"WARN: summary failed: {e}, continuing...", err=True)

    # --- Save checkpoint ---
    _save_update_checkpoint(project_dir)
    click.echo(f"\nCheckpoint saved (since: {date.today().isoformat()}).", err=True)

    # --- Report ---
    # Count new beliefs
    try:
        network = _load_network()
        post_run_ids = set(network.get("nodes", {}).keys())
        new_beliefs = post_run_ids - pre_run_ids
        click.echo(f"New beliefs: {len(new_beliefs)}", err=True)
    except Exception:
        pass

    click.echo(f"\n{'=' * 40}", err=True)
    if errors:
        click.echo(f"Update completed with {len(errors)} warning(s):", err=True)
        for err in errors:
            click.echo(f"  - {err}", err=True)
    else:
        click.echo("Update completed successfully.", err=True)
    click.echo(f"{'=' * 40}", err=True)


def _fetch_issues(source, config, state, labels, limit, page, since):
    """Fetch issues from source with since filtering."""
    platform = config["platform"]
    if platform == "jira":
        return source.list_issues(state=state, labels=labels, limit=limit,
                                  page=page, since=since)
    elif platform == "gitlab":
        return source.list_issues(state=state, labels=labels, limit=limit,
                                  page=page, since=since)
    else:
        return source.list_issues(state=state, labels=labels, limit=limit,
                                  since=since)


def _run_scan_step(ctx, config, source, issues, project_name,
                   state, limit, page, project_dir, model, timeout):
    """Run the scan LLM step on a batch of fetched issues."""
    click.echo(f"  Fetched {len(issues)} issues", err=True)

    # Fetch PRs for platforms that support them
    prs = []
    if config["platform"] in ("github", "gitlab") and hasattr(source, "list_prs"):
        try:
            prs = source.list_prs(state=state or "open", limit=limit)
            if prs:
                click.echo(f"  Fetched {len(prs)} pull requests", err=True)
        except Exception as e:
            click.echo(f"  Warning: Could not fetch PRs: {e}", err=True)

    issues_text = "\n\n".join(issue.to_prompt_text() for issue in issues)
    prs_text = ""
    if prs:
        prs_text = "\n\n".join(pr.to_prompt_text() for pr in prs)

    prompt = build_scan_prompt(
        issues_text=issues_text,
        prs_text=prs_text,
        project_name=project_name,
        platform=config["platform"],
        issue_count=len(issues),
        pr_count=len(prs),
        state=state,
    )

    click.echo(f"  Running {model}...", err=True)
    result = asyncio.run(invoke(prompt, model, timeout=timeout))

    short_name = project_name.split("//")[-1] if "//" in project_name else project_name
    safe_name = short_name.replace("/", "-")
    state_suffix = f"-{state}" if state and state not in ("open", "opened") else ""
    page_suffix = f"-p{page}" if page > 1 else ""
    _create_entry(f"update-{safe_name}{state_suffix}{page_suffix}",
                  f"Update: {project_name} ({state or 'all'}, page {page})", result)
    _enqueue_topics(result, source=f"update:{project_name}", project_dir=project_dir)
    _report_beliefs(result)
    _cache_issues(issues, project_dir)
    _emit(ctx, result)


if __name__ == "__main__":
    cli()
