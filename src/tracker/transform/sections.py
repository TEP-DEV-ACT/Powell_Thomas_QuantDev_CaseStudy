"""Extract Item 1A (Risk Factors) and Item 7 (MD&A) from a 10-K's HTML,
chunk them for full-text search, and store into filing_sections/filing_chunks.

Two real-world messiness problems this guards against (found by spot-checking
NVDA/AAPL/GOOGL/MSFT/ETN filings against this parser):

1. Table-of-contents false positives, and inline back-references to "Item 1A"
   inside the risk-factor prose itself, both produce spurious regex matches.
   Instead of trusting "the last match" (which breaks on ETN's own
   self-referencing cybersecurity risk factor), every candidate start/end
   pairing is scored by resulting section length and the longest wins — real
   section headings bound a large span; TOC entries and cross-references
   bound a tiny one.
2. Some filers (MSFT) render heading text as adjacent single-letter/short
   spans for kerning ("RIS" + "K" as separate text nodes), which breaks a
   whitespace-tolerant regex. Matching is done against a fully whitespace-
   stripped copy of the text with a position index back to the original, so
   spacing artifacts can't split a heading word apart.
3. Some filers (ETN) use an "integrated" 10-K where Item 7 is a one-line
   pointer ("Information required by this Item is presented in
   'Management's Discussion and Analysis...' of this Form 10-K") to a
   standalone, unnumbered heading elsewhere in the document. When the direct
   Item-N heading match fails to produce a real section, we extract the
   quoted target title from the pointer sentence and locate that heading's
   standalone occurrence instead.
"""
import logging
import re

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MIN_SECTION_CHARS = 1500
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150

# Despaced patterns (matched against a copy of the text with ALL whitespace
# removed) so letter-spacing artifacts inside a heading can't break the match.
ITEM_1A_START = re.compile(r"item1a\.?[—:-]?riskfactors", re.I)
ITEM_1A_END_PATTERNS = [
    re.compile(r"item1b\.?[—:-]?unresolvedstaffcomments", re.I),
    re.compile(r"item2\.?[—:-]?properties", re.I),
]
ITEM_7_START = re.compile(r"item7\.?[—:-]?management.?sdiscussion", re.I)
ITEM_7_END_PATTERNS = [
    re.compile(r"item7a\.?[—:-]?quantitative", re.I),
    re.compile(r"item8\.?[—:-]?financialstatements", re.I),
]

SECTION_SPECS = {
    "1A": (ITEM_1A_START, ITEM_1A_END_PATTERNS),
    "7": (ITEM_7_START, ITEM_7_END_PATTERNS),
}

# Loose (normally-spaced) patterns used only to locate approximate positions
# of "Item N" pointer sentences for the integrated-10-K fallback.
_LOOSE_ITEM_RE = {
    "1A": re.compile(r"item\s*1a\b", re.I),
    "1B": re.compile(r"item\s*1b\b", re.I),
    "2": re.compile(r"item\s*2\b", re.I),
    "7": re.compile(r"item\s*7\b(?!a)", re.I),
    "7A": re.compile(r"item\s*7a\b", re.I),
    "8": re.compile(r"item\s*8\b", re.I),
}
_END_ITEM_KEYS = {"1A": ["1B", "2"], "7": ["7A", "8"]}

_POINTER_TARGET_RE = re.compile(
    r"(?:presented|described|discussed|set\s+forth|included)\s+in\s+"
    r'(?:“([^”]{5,150})”|"([^"]{5,150})")',
    re.I,
)


def _is_numeric_table(table) -> bool:
    text = table.get_text()
    alnum = [c for c in text if c.isalnum()]
    if len(alnum) < 20:
        return True
    digits = sum(1 for c in alnum if c.isdigit())
    return (digits / len(alnum)) > 0.4


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    for table in soup.find_all("table"):
        if _is_numeric_table(table):
            table.decompose()

    raw = soup.get_text("\n")
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in raw.split("\n")]
    return "\n".join(line for line in lines if line)


def _despace(text: str) -> tuple[str, list[int]]:
    """Strip all whitespace; return the despaced string plus a map from each
    despaced-string index back to its position in the original `text`."""
    chars, index_map = [], []
    for i, c in enumerate(text):
        if not c.isspace():
            chars.append(c)
            index_map.append(i)
    return "".join(chars), index_map


def _map_pos(index_map: list[int], idx: int, text_len: int) -> int:
    return index_map[idx] if idx < len(index_map) else text_len


def _best_span(despaced, index_map, text_len, start_pattern, end_patterns):
    """Try every start-pattern match and every start/end pairing; return the
    (start_pos, end_pos) in original-text coordinates with the largest span,
    since real headings bound a large section while TOC lines and inline
    cross-references bound a tiny one."""
    starts = list(start_pattern.finditer(despaced))
    if not starts:
        return None

    best = None
    for sm in starts:
        start_idx = sm.end()
        end_idx = len(despaced)
        for end_pattern in end_patterns:
            ends = [m for m in end_pattern.finditer(despaced) if m.start() > start_idx]
            if ends:
                end_idx = min(end_idx, ends[0].start())
        span = end_idx - start_idx
        if best is None or span > best[0]:
            best = (span, _map_pos(index_map, start_idx, text_len), _map_pos(index_map, end_idx, text_len))
    return best[1], best[2]


def _pointer_target(flat: str, item_key: str) -> str | None:
    for m in _LOOSE_ITEM_RE[item_key].finditer(flat):
        target = _POINTER_TARGET_RE.search(flat[m.end():m.end() + 400])
        if target:
            return (target.group(1) or target.group(2)).strip()
    return None


def _find_last_occurrence(flat: str, phrase: str, after: int = 0) -> int | None:
    words = re.findall(r"\w+", phrase)
    if not words:
        return None
    pattern = re.compile(r"\W*".join(re.escape(w) for w in words), re.I)
    matches = [m for m in pattern.finditer(flat) if m.start() >= after]
    return matches[-1].start() if matches else None


def _pointer_fallback(flat: str, text_len: int, item_key: str, end_keys: list[str]) -> tuple[int, int] | None:
    """Integrated-10-K fallback: follow "presented in '<title>'" pointers to
    the standalone heading they reference, for both the section's own start
    and the next item's pointer (used as the end boundary)."""
    start_target = _pointer_target(flat, item_key)
    if not start_target:
        return None
    # The pointer sentence itself will match too; we want a later, distinct heading.
    pointer_pos = _LOOSE_ITEM_RE[item_key].search(flat).start()
    start_pos = _find_last_occurrence(flat, start_target, after=pointer_pos + 1)
    if start_pos is None or start_pos <= pointer_pos:
        return None

    end_pos = text_len
    for end_key in end_keys:
        end_target = _pointer_target(flat, end_key)
        if end_target:
            candidate = _find_last_occurrence(flat, end_target, after=start_pos + 1)
            if candidate is not None:
                end_pos = min(end_pos, candidate)
                break
    return start_pos, end_pos


def _extract_section(text: str, item: str, start_pattern, end_patterns) -> str | None:
    despaced, index_map = _despace(text)
    span = _best_span(despaced, index_map, len(text), start_pattern, end_patterns)

    if span is None or (span[1] - span[0]) < MIN_SECTION_CHARS:
        flat = text.replace("\n", " ")
        fallback = _pointer_fallback(flat, len(text), item, _END_ITEM_KEYS[item])
        if fallback is not None and (fallback[1] - fallback[0]) > (0 if span is None else span[1] - span[0]):
            span = fallback

    if span is None:
        return None
    section = text[span[0]:span[1]].strip()
    return section or None


def extract_sections(html: str) -> dict:
    """Returns {item: text} for whichever of '1A'/'7' were found."""
    text = html_to_text(html)
    results = {}
    for item, (start_pattern, end_patterns) in SECTION_SPECS.items():
        section = _extract_section(text, item, start_pattern, end_patterns)
        if section is None:
            logger.warning("Item %s: no match found", item)
            continue
        if len(section) < MIN_SECTION_CHARS:
            logger.warning(
                "Item %s: parsed section only %d chars (below %d threshold)",
                item, len(section), MIN_SECTION_CHARS,
            )
        results[item] = section
    return results


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    paragraphs = [p for p in text.split("\n") if p]
    chunks = []
    buffer = ""
    for para in paragraphs:
        if buffer and len(buffer) + 1 + len(para) > chunk_size:
            chunks.append(buffer)
            buffer = buffer[-overlap:] if overlap else ""
        buffer = f"{buffer} {para}".strip() if buffer else para
    if buffer:
        chunks.append(buffer)
    return chunks


def extract_and_store_sections(conn, filing_id: int, html: str) -> dict:
    sections = extract_sections(html)
    counts = {}
    with conn.cursor() as cur:
        for item, text in sections.items():
            cur.execute(
                """
                INSERT INTO filing_sections (filing_id, item, char_count, text)
                VALUES (%(filing_id)s, %(item)s, %(char_count)s, %(text)s)
                ON CONFLICT (filing_id, item) DO UPDATE SET
                    char_count = EXCLUDED.char_count, text = EXCLUDED.text
                RETURNING id
                """,
                {"filing_id": filing_id, "item": item, "char_count": len(text), "text": text},
            )
            section_id = cur.fetchone()["id"]
            cur.execute("DELETE FROM filing_chunks WHERE section_id = %(section_id)s", {"section_id": section_id})
            chunks = chunk_text(text)
            for idx, chunk in enumerate(chunks):
                cur.execute(
                    """
                    INSERT INTO filing_chunks (section_id, chunk_index, text)
                    VALUES (%(section_id)s, %(chunk_index)s, %(text)s)
                    """,
                    {"section_id": section_id, "chunk_index": idx, "text": chunk},
                )
            counts[item] = {"char_count": len(text), "chunks": len(chunks)}
    conn.commit()
    return counts
