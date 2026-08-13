"""Item 1A/7 parsing tests, including the real-world failure modes found by
spot-checking actual filings (see transform/sections.py's module docstring):
the table-of-contents trap, letter-spaced headings, and pointer-style
"integrated" 10-Ks that reference a standalone heading elsewhere."""
import os

from tracker.transform.sections import chunk_text, extract_sections

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "sample_10k.html")


def _load_fixture() -> str:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def test_extracts_both_sections_from_fixture():
    sections = extract_sections(_load_fixture())
    assert "1A" in sections
    assert "7" in sections


def test_item_1a_skips_toc_and_lands_on_real_heading():
    sections = extract_sections(_load_fixture())
    text = sections["1A"]
    # The TOC line ("Item 1A. Risk Factors  17") must not be what got captured.
    assert "Cybersecurity risk" in text
    assert "Supply chain risk" in text
    # Should not spill into Item 1B's content.
    assert "Item 1B" not in text or text.index("Item 1B") > len(text) - 5


def test_item_1a_survives_inline_self_reference():
    # The fixture's risk-factor prose contains a parenthetical-style
    # back-reference to "Item 1A. Risk Factors" inside its own body text —
    # this must not be mistaken for a second, shorter section boundary.
    sections = extract_sections(_load_fixture())
    assert "Regulatory risk" in sections["1A"]


def test_item_7_captures_mdna_not_toc():
    sections = extract_sections(_load_fixture())
    text = sections["7"]
    assert "Revenue increased 12%" in text
    assert "Gross margin expanded" in text


def test_numeric_table_is_dropped_from_extracted_text():
    sections = extract_sections(_load_fixture())
    # The trailing financial-statement-style table (revenue/net income
    # figures) should be stripped before section text is captured.
    assert "1,234,567" not in sections.get("7", "") + sections.get("1A", "")


def test_letter_spaced_heading_still_matches():
    # Some filers (observed on MSFT) render a heading as adjacent
    # single-letter/short spans for kerning, e.g. "RIS" + "K" as separate
    # text nodes — this becomes "RIS K FACTORS" once whitespace-joined.
    html = """
    <html><body>
    <p>Item 1A. Risk Factors 5 Item 1B. Unresolved Staff Comments 9</p>
    <h2>Item 1A <span>RIS</span><span>K FACTORS</span></h2>
    <p>""" + ("Our operations are subject to a variety of risks. " * 60) + """</p>
    <h2>Item 1B. Unresolved Staff Comments</h2>
    <p>None.</p>
    </body></html>
    """
    sections = extract_sections(html)
    assert "1A" in sections
    assert "subject to a variety of risks" in sections["1A"]


def test_pointer_style_integrated_10k_follows_reference():
    # Some filers (observed on ETN) present Item 7 as a one-line pointer to a
    # standalone, unnumbered heading elsewhere in the document instead of
    # directly attaching the MD&A prose to the "Item 7" heading itself.
    body_text = "Revenue grew due to strong demand across all segments. " * 40
    html = f"""
    <html><body>
    <p>Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations 12</p>
    <p>Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations.
    Information required by this Item is presented in &ldquo;Management's Discussion and Analysis of
    Financial Condition and Results of Operations&rdquo; of this Form 10-K.
    Item 7A. Quantitative and Qualitative Disclosures about Market Risk. Information regarding market
    risk is presented in &ldquo;Market Risk Disclosure&rdquo; of this Form 10-K.</p>
    <h2>MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS</h2>
    <p>{body_text}</p>
    <h2>MARKET RISK DISCLOSURE</h2>
    <p>We are exposed to interest rate risk.</p>
    </body></html>
    """
    sections = extract_sections(html)
    assert "7" in sections
    assert "Revenue grew due to strong demand" in sections["7"]
    assert "interest rate risk" not in sections["7"]


def test_chunk_text_respects_size_and_overlap():
    text = "\n".join(f"Paragraph number {i} with some filler content." for i in range(50))
    chunks = chunk_text(text, chunk_size=200, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 260 for c in chunks)  # size + a little slack for overlap merge
