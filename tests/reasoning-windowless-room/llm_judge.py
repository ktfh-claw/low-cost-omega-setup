"""A-gate LLM judge (v15b, directive 2026-10-26 22:56 UTC).

The answer-substance check is no longer deterministic keyword grading
(v2–v14: A_SKY/A_FABRICATED/A_NO_INABILITY keyword lexicons). A single
OpenAI chat-completions-compatible call now judges whether the case's
FINAL ANSWER line is substantively correct:

  - the judge sees ONLY the case question, the ground truth
    (expected answer + answer-only grading guidance from facts.py),
    and the FINAL ANSWER text — never the reasoning trace, receipts,
    or any other gate evidence;
  - the reply must contain the token CORRECT or INCORRECT;
  - everything else in the harness stays deterministic.

Default endpoint: ASI:One (https://api.asi1.ai/v1, model asi1-ultra) —
the same OpenAI-compatible provider the Omega agent itself uses. API key
resolution: explicit --judge-api-key arg > ASIONE_API_KEY / OPENAI_API_KEY
env > the Omega deployment's runtime.env (the harness runs on the OVH
host). The key is never logged, committed, or written to artifacts.
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
HTTP_ATTEMPTS = 2          # first attempt + one retry on transient errors
RETRY_SLEEP_S = 2.0

DEFAULT_RUNTIME_ENV = "/home/ubuntu/omega-curiosity/runtime.env"

SYSTEM_PROMPT = (
    "You are a strict, minimal answer grader for a reasoning benchmark. "
    "You get a JSON object with: the test question, the ground-truth "
    "expected answer with grading guidance, and a candidate final answer. "
    "Judge ONLY whether the candidate answer is substantively correct for "
    "the question, following the grading guidance. Ignore style, grammar, "
    "and any reasoning, evidence, queries or citations the candidate text "
    "may mention. Reply with exactly one word on the first line: CORRECT "
    "or INCORRECT. You may add one short sentence after it."
)


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
    """Judge payload: question + ground truth + answer line ONLY."""
    payload = {
        "question": case.get("question", ""),
        "expected_answer": case.get("expected_answer", ""),
        "grading_guidance": case.get("grading", ""),
        "final_answer": final_answer,
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def parse_verdict(text: str) -> bool:
    """First CORRECT/INCORRECT token wins; unparseable reply raises."""
    m = re.search(r"\b(CORRECT|INCORRECT)\b", text or "", re.IGNORECASE)
    if not m:
        raise JudgeUnavailable(f"unparseable judge reply: {(text or '')[:120]!r}")
    return m.group(1).upper() == "CORRECT"


def _chat(base_url: str, model: str, api_key: str, messages: list[dict],
          timeout: float) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 40,
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
                    "judge_verdict": "CORRECT" if ok else "INCORRECT",
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
