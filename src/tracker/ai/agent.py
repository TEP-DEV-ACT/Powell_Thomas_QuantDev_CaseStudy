"""The Claude tool-use agent loop. Routing is the model's own choice of
tools — surfaced to the caller as `trace` so the answer is auditable against
what was actually retrieved.
"""
import logging

import anthropic

from tracker.ai.prompts import SYSTEM_PROMPT
from tracker.ai.tools import build_tools
from tracker.config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ANTHROPIC_MODEL

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


def ask(question: str) -> dict:
    logger.info("AI chat: question=%r", question)
    trace: list = []
    tools = build_tools(trace)
    runner = _client().beta.messages.tool_runner(
        model=ANTHROPIC_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": question}],
        tools=tools,
        max_iterations=MAX_ITERATIONS,
    )
    final = runner.until_done()
    answer = "".join(block.text for block in final.content if block.type == "text")
    citations = _extract_citations(trace)
    logger.info(
        "AI chat: answered in %d chars, %d tool calls, %d citations",
        len(answer), len(trace), len(citations),
    )
    return {"answer": answer, "trace": trace, "citations": citations}
