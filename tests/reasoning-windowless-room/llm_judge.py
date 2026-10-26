"""A-gate LLM judge (v16, directive 2026-10-26 22:56 UTC follow-up).

Simplified single-prompt design per Balázs's directive ("instead of
that"): construct ONE simple prompt that contains the test prompt (the
case question), the Omega agent's final answer, and the correct answer
we expect; send it as a single OpenAI-compatible chat-completions
request; the endpoint replies with a simple TRUE or FALSE; the script
parses that verdict and uses it as the blocking A-gate.

  - messages = ONE user message (no system prompt, no JSON payload):
    question + expected answer + agent answer + "Reply with exactly
    one word: TRUE or FALSE";
  - endpoint configurable via the run_benchmark CLI
    (--judge-base-url / --judge-model / --judge-api-key /
    --judge-timeout); defaults reuse the Omega agent's own setup:
    ASI:One https://api.asi1.ai/v1, model asi1-ultra, API key resolved
    from the Omega deployment's runtime.env (ASIONE_API_KEY) — the
    same key the Omega agent uses;
  - the judge sees ONLY those three items — never the reasoning trace,
    receipts, queries, or citations (input restriction preserved from
    v15b);
  - fail-safe: unresolvable key / HTTP failure after one retry /
    unparseable reply -> JudgeUnavailable -> blocking
    A_JUDGE_UNAVAILABLE (an unjudged answer can never pass).
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request

DEFAULT_BASE_URL = "https://api.asi1.ai/v1"
DEFAULT_MODEL = "asi1-ultra"
DEFAULT_TIMEOUT = 60.0
MAX_TOKENS = 512          # live evidence 2026-10-26: asi1-ultra consumed a
                         # 16-token budget pre-content (finish_reason=length,
                         # empty message) — the parser takes the first
                         # TRUE/FALSE token, so headroom is harmless
HTTP_ATTEMPTS = 2          # first attempt + one retry on transient errors
RETRY_SLEEP_S = 2.0

DEFAULT_RUNTIME_ENV = "/home/ubuntu/omega-curiosity/runtime.env"


class JudgeUnavailable(Exception):
    """The judge LLM call could not be made or parsed (harness-side error)."""


def resolve_api_key(explicit: str = "",
                    runtime_env_path: str = DEFAULT_RUNTIME_ENV) -> tuple[str, str]:
    """Return (api_key, source). Precedence: arg > env > runtime.env."""
    if explicit and explicit.strip():
        return explicit.strip(), "arg"
    for var in ("ASIONE_API_KEY", "OPENAI_API_KEY", "WR_JUDGE_API_KEY"):
        v = os.environ.get(var, "").strip()
        if v:
            return v, "env"
    try:
        with open(runtime_env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("ASIONE_API_KEY="):
                    v = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if v:
                        return v, "runtime.env"
    except OSError:
        pass
    raise JudgeUnavailable(
        "no judge API key found (arg / ASIONE_API_KEY / OPENAI_API_KEY / "
        f"{runtime_env_path})")


def build_messages(case: dict, final_answer: str) -> list[dict]:
    """Judge payload: ONE user message with the test prompt (question),
    the agent's final answer, and the expected correct answer."""
    prompt = (
        "You are grading an answer in a reasoning benchmark.\n\n"
        "Question given to the agent:\n"
        f"{case.get('question', '')}\n\n"
        "Expected correct answer:\n"
        f"{case.get('expected_answer', '')}\n\n"
        "The agent's final answer:\n"
        f"{final_answer}\n\n"
        "Is the agent's final answer correct — does it match the expected "
        "answer in substance? Judge only whether the answer is right, not "
        "its style or wording. Reply with exactly one word: TRUE or FALSE."
    )
    return [{"role": "user", "content": prompt}]


def parse_verdict(text: str) -> bool:
    """First TRUE/FALSE token wins; TRUE = correct. Junk raises."""
    m = re.search(r"\b(TRUE|FALSE)\b", text or "", re.IGNORECASE)
    if not m:
        raise JudgeUnavailable(f"unparseable judge reply: {(text or '')[:120]!r}")
    return m.group(1).upper() == "TRUE"


def _chat(base_url: str, model: str, api_key: str, messages: list[dict],
          timeout: float) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": MAX_TOKENS,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = ((data.get("choices") or [{}])[0]
               .get("message", {}).get("content", ""))
    if not content:
        raise JudgeUnavailable(f"empty judge reply: {str(data)[:120]}")
    return content


def make_judge(base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL,
               api_key: str = "", timeout: float = DEFAULT_TIMEOUT,
               runtime_env_path: str = DEFAULT_RUNTIME_ENV):
    """Build the judge callable: (case, final_answer) -> (ok, detail).

    Raises JudgeUnavailable at construction when no API key resolves.
    """
    key, source = resolve_api_key(api_key, runtime_env_path)

    def judge(case: dict, final_answer: str) -> tuple[bool, dict]:
        messages = build_messages(case, final_answer)
        last_err: Exception | None = None
        for _ in range(HTTP_ATTEMPTS):
            try:
                t0 = time.monotonic()
                content = _chat(base_url, model, key, messages, timeout)
                ok = parse_verdict(content)
                return ok, {
                    "judge_verdict": "TRUE" if ok else "FALSE",
                    "model": model,
                    "base_url": base_url,
                    "key_source": source,
                    "latency_s": round(time.monotonic() - t0, 2),
                    "raw": content.strip()[:200],
                }
            except JudgeUnavailable:
                raise                      # parse errors are not transient
            except Exception as e:          # HTTP/timeout: retry once
                last_err = e
                time.sleep(RETRY_SLEEP_S)
        raise JudgeUnavailable(f"judge call failed: {last_err}")

    return judge
