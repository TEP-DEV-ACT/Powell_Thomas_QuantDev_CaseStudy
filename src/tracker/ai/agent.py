"""The Claude tool-use agent loop. Routing is the model's own choice of
tools — surfaced to the caller as `trace` so the answer is auditable against
what was actually retrieved.
"""
import logging
from datetime import date

import anthropic

from tracker.ai.prompts import build_system_prompt
from tracker.ai.tools import build_tools
from tracker.config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ANTHROPIC_MODEL
from tracker.metrics.queries import latest_common_fiscal_year

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10
MAX_TOKENS = 1500


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, base_url=ANTHROPIC_BASE_URL)


def _extract_citations(trace: list) -> list[dict]:
    citations, seen = [], set()
    for entry in trace:
        if entry["tool"] != "search_filings" or not isinstance(entry["result"], list):
            continue
        for r in entry["result"]:
            key = (r.get("ticker"), r.get("fiscal_year"), r.get("item"), r.get("accession_no"))
            if key in seen:
                continue
            seen.add(key)
            citations.append(
                {
                    "label": f"{r.get('ticker')} FY{r.get('fiscal_year')} Item {r.get('item')} ({r.get('accession_no')})",
                    "url": r.get("primary_doc_url"),
                }
            )
    return citations


def ask(question: str, history: list[dict] | None = None) -> dict:
    """Answer `question`, optionally in the context of prior turns.

    `history` is the plain-text transcript so far — alternating user/assistant
    messages — so follow-ups ("and for NVDA?") resolve. Only the final text of
    each past turn is replayed, not its tool calls: re-sending the tool blocks
    would cost a lot of tokens to tell the model things it can just look up
    again, and `trace` stays scoped to the turn the caller is asking about.
    The caller is responsible for validating and bounding it.
    """
    logger.info("AI chat: question=%r history=%d turns", question, len(history or []))
    trace: list = []
    tools = build_tools(trace)
    try:
        common_fy = latest_common_fiscal_year()
    except Exception:
        logger.exception("AI chat: could not resolve latest_common_fiscal_year, omitting from prompt")
        common_fy = None
    system_prompt = build_system_prompt(today=date.today().isoformat(), latest_common_fiscal_year=common_fy)
    # Individual tool failures are already caught and turned into structured
    # {"error": ...} results inside build_tools (ai/tools.py) so a single bad
    # DB read doesn't abort the turn. What's caught here is everything
    # outside that: the Anthropic API call itself (auth, rate limit, network,
    # a malformed model response) — distinguished so the caller (routes_api
    # /api/ask) can show something more useful than a raw exception string.
    try:
        runner = _client().beta.messages.tool_runner(
            model=ANTHROPIC_MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[*(history or []), {"role": "user", "content": question}],
            tools=tools,
            max_iterations=MAX_ITERATIONS,
        )
        final = runner.until_done()
    except anthropic.RateLimitError as exc:
        logger.warning("AI chat: rate limited: %s", exc)
        raise RuntimeError("The AI service is rate-limited right now — please try again shortly.") from exc
    except anthropic.APIConnectionError as exc:
        logger.error("AI chat: could not reach the AI service: %s", exc)
        raise RuntimeError("Could not reach the AI service — check the network/proxy configuration.") from exc
    except anthropic.APIStatusError as exc:
        logger.error("AI chat: AI service returned an error: %s", exc)
        raise RuntimeError(f"The AI service returned an error (status {exc.status_code}).") from exc
    except anthropic.APIError as exc:
        logger.exception("AI chat: unexpected Anthropic API error")
        raise RuntimeError("The AI service failed unexpectedly.") from exc

    answer = "".join(block.text for block in final.content if block.type == "text")
    citations = _extract_citations(trace)
    logger.info(
        "AI chat: answered in %d chars, %d tool calls, %d citations",
        len(answer), len(trace), len(citations),
    )
    return {"answer": answer, "trace": trace, "citations": citations}
