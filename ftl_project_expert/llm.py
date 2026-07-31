"""Model invocation for project expert.

Cost tracking: CLI models use --output-format json to capture token
counts and costs. Use get_cost_summary() / format_cost_summary() to
retrieve accumulated stats.
"""

import asyncio
import json
import os
import shutil
import threading

MODEL_COMMANDS: dict[str, list[str]] = {
    "claude": ["claude", "-p", "--output-format", "json"],
    "gemini": ["gemini", "--skip-trust", "-o", "json", "-p", ""],
}

DEFAULT_TIMEOUT = 600

_cost_lock = threading.Lock()

_cost_tracker = {
    "calls": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "total_cost_usd": 0.0,
    "by_model": {},
}


def reset_cost_tracker():
    """Reset accumulated cost/token stats."""
    with _cost_lock:
        _cost_tracker["calls"] = 0
        _cost_tracker["input_tokens"] = 0
        _cost_tracker["output_tokens"] = 0
        _cost_tracker["total_cost_usd"] = 0.0
        _cost_tracker["by_model"] = {}


def get_cost_summary() -> dict:
    """Return accumulated cost/token stats across all LLM calls."""
    import copy
    with _cost_lock:
        return copy.deepcopy(_cost_tracker)


def format_cost_summary() -> str:
    """Format cost summary as a human-readable string."""
    with _cost_lock:
        s = _cost_tracker
        if s["calls"] == 0:
            return ""
        parts = []
        if s["total_cost_usd"] > 0:
            parts.append(f"${s['total_cost_usd']:.4f}")
        parts.append(f"{s['input_tokens']:,} input + {s['output_tokens']:,} output tokens")
        parts.append(f"{s['calls']} call(s)")
        return "Cost: " + " | ".join(parts)


def _record_cost(model: str, input_tokens: int, output_tokens: int, cost_usd: float):
    """Record token/cost stats from one LLM call."""
    with _cost_lock:
        _cost_tracker["calls"] += 1
        _cost_tracker["input_tokens"] += input_tokens
        _cost_tracker["output_tokens"] += output_tokens
        _cost_tracker["total_cost_usd"] += cost_usd

        if model not in _cost_tracker["by_model"]:
            _cost_tracker["by_model"][model] = {
                "calls": 0, "input_tokens": 0, "output_tokens": 0, "total_cost_usd": 0.0,
            }
        m = _cost_tracker["by_model"][model]
        m["calls"] += 1
        m["input_tokens"] += input_tokens
        m["output_tokens"] += output_tokens
        m["total_cost_usd"] += cost_usd


def _parse_cli_json(output: str, model: str) -> str:
    """Parse JSON output from CLI, extract response text and record costs.

    Falls back to returning raw output if JSON parsing fails.
    """
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return output

    if not isinstance(data, dict):
        return output

    if model.startswith("gemini") or model.startswith("gemini:"):
        text = data.get("response", output)
        stats = data.get("stats", {})
        input_tokens = 0
        output_tokens = 0
        for model_stats in stats.get("models", {}).values():
            tokens = model_stats.get("tokens", {})
            input_tokens += tokens.get("input", 0)
            output_tokens += tokens.get("candidates", 0)
        _record_cost(model, input_tokens, output_tokens, 0.0)
        return text

    text = data.get("result", output)
    usage = data.get("usage", {})
    input_tokens = (usage.get("input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0)
                    + usage.get("cache_read_input_tokens", 0))
    output_tokens = usage.get("output_tokens", 0)
    cost_usd = data.get("total_cost_usd", 0.0)
    _record_cost(model, input_tokens, output_tokens, cost_usd)
    return text


def check_model_available(model: str) -> bool:
    """Check if a model's CLI is available."""
    if model not in MODEL_COMMANDS:
        return False
    cmd = MODEL_COMMANDS[model][0]
    return shutil.which(cmd) is not None


async def invoke(prompt: str, model: str = "claude", timeout: int = DEFAULT_TIMEOUT) -> str:
    """Invoke model via CLI, piping prompt through stdin."""
    if model not in MODEL_COMMANDS:
        raise ValueError(f"Unknown model: {model}. Available: {list(MODEL_COMMANDS.keys())}")

    cmd = MODEL_COMMANDS[model]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(prompt.encode()),
            timeout=timeout,
        )
    except TimeoutError:
        proc.kill()
        raise TimeoutError(f"Model {model} timed out after {timeout}s") from None

    if proc.returncode != 0:
        detail = stderr.decode().strip() or stdout.decode().strip() or f"exit code {proc.returncode}"
        raise RuntimeError(f"Model {model} failed: {detail}")

    return _parse_cli_json(stdout.decode(), model)


def invoke_sync(prompt: str, model: str = "claude", timeout: int = DEFAULT_TIMEOUT) -> str:
    """Synchronous wrapper around invoke."""
    return asyncio.run(invoke(prompt, model, timeout))


async def invoke_concurrent(
    prompts: list[str],
    model: str = "claude",
    timeout: int = DEFAULT_TIMEOUT,
    max_concurrent: int = 3,
) -> list[str | Exception]:
    """Invoke model on multiple prompts concurrently.

    Returns a list in the same order as prompts. Each element is either
    the model's response string or the Exception that occurred.
    """
    sem = asyncio.Semaphore(max_concurrent)

    async def _guarded(prompt: str) -> str:
        async with sem:
            return await invoke(prompt, model, timeout)

    return await asyncio.gather(
        *[_guarded(p) for p in prompts],
        return_exceptions=True,
    )


def invoke_concurrent_sync(
    prompts: list[str],
    model: str = "claude",
    timeout: int = DEFAULT_TIMEOUT,
    max_concurrent: int = 3,
) -> list[str | Exception]:
    """Synchronous wrapper around invoke_concurrent."""
    return asyncio.run(invoke_concurrent(prompts, model, timeout, max_concurrent))
