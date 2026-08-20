r"""Tests for math normalization in scroll bodies (`src/scrolls/mathtext.py`).

MediaWiki's `explaintext` extract renders a `<math>` tag as its MathML
fallback — one symbol per indented line — followed by the real TeX in a
`{\displaystyle ...}` wrapper. Left alone that is unreadable to a human and
noise to an agent; 8,280 of them landed in the library's first full capture.
"""

from scrolls.mathtext import normalize_math

# The exact shape MediaWiki produces, reproduced from a captured scroll
# (`modus-ponens.md`) so the fixtures cannot drift from reality.
DISPLAY = r"""The modus ponens rule may be written in sequent notation as

  
    
      
        P
        →
        Q
      
    
    {\displaystyle P\to Q,\;P\;\;\vdash \;\;Q}
  

where P, Q and P → Q are statements."""

INLINE = r"""Logical equivalence becomes identity, so that when 
  
    
        ¬
        P
      
    
    {\displaystyle \neg {(P\wedge Q)}}
  
 and 
  
    
        ¬
        Q
    
    {\displaystyle \neg {P}\vee \neg {Q}}
  
, for instance, are equivalent."""


def test_a_standalone_block_becomes_display_math():
    out = normalize_math(DISPLAY)

    assert r"$$P\to Q,\;P\;\;\vdash \;\;Q$$" in out
    assert "displaystyle" not in out


def test_the_mathml_token_dump_is_removed():
    out = normalize_math(DISPLAY)

    # no line may survive as a lone indented symbol, and no whitespace-only
    # spacer may remain; the arrow in the closing prose is real content
    assert not [ln for ln in out.split("\n") if ln != ln.strip() and ln.strip()]
    assert not [ln for ln in out.split("\n") if ln != "" and not ln.strip()]
    assert out.endswith("where P, Q and P → Q are statements.")


def test_surrounding_prose_and_paragraph_breaks_survive():
    out = normalize_math(DISPLAY)
    lines = out.split("\n")

    assert lines[0] == "The modus ponens rule may be written in sequent notation as"
    assert lines[1] == ""
    assert lines[2].startswith("$$")
    assert lines[3] == ""
    assert lines[4] == "where P, Q and P → Q are statements."


def test_math_inside_a_sentence_becomes_inline_math():
    out = normalize_math(INLINE)

    assert "$$" not in out
    assert r"$\neg {(P\wedge Q)}$" in out


def test_a_sentence_broken_by_math_is_rejoined_into_one_line():
    """The prose fragments between two inline formulas are one sentence."""
    out = normalize_math(INLINE)

    assert out == (
        "Logical equivalence becomes identity, so that when "
        r"$\neg {(P\wedge Q)}$ and $\neg {P}\vee \neg {Q}$"
        ", for instance, are equivalent."
    )


def test_textstyle_is_treated_the_same_as_displaystyle():
    out = normalize_math("when \n  \n    {\\textstyle P}\n  \n holds")

    assert out == "when $P$ holds"


def test_an_escaped_brace_does_not_end_the_formula():
    r"""`\left\{` is a literal brace, not a group — 3 corpus blocks rely on it."""
    tex = r"\left\{{\begin{aligned}4x+y&=6x\end{aligned}}\right."
    out = normalize_math("that is,\n\n  \n    {\\displaystyle " + tex + "}\n  \n\nsolved.")

    assert f"$${tex}$$" in out
    assert "solved." in out


def test_text_without_math_is_returned_unchanged():
    text = "A plain scroll.\n\nWith two paragraphs.\n"

    assert normalize_math(text) == text


def test_indented_prose_is_left_alone_when_no_formula_follows():
    r"""Only lines immediately preceding a `{\displaystyle}` marker are noise."""
    text = "intro\n\n    a code-ish indented line\n\nouttro"

    assert normalize_math(text) == text


# --- literal dollars ----------------------------------------------------------
#
# Introducing `$` as a math delimiter makes every currency amount in prose a
# potential delimiter. The captured library holds 990 literal `$` across 115
# scrolls — "Nvidia" alone has 65 — and 10 scrolls carry both dollars and math,
# where an unescaped pair would swallow the sentence between them.


def test_a_currency_amount_is_escaped_so_it_is_not_read_as_math():
    out = normalize_math("With $40,000 in the bank.")

    assert out == r"With \$40,000 in the bank."


def test_two_currency_amounts_do_not_pair_into_a_formula():
    text = "raised $2 billion in 2020 and $3 billion in 2021"
    out = normalize_math(text)

    # neither dollar may remain a live delimiter
    assert out.replace(r"\$", "").count("$") == 0
    assert "2 billion in 2020 and" in out


def test_dollars_are_escaped_even_in_a_scroll_with_no_math():
    """The delimiter convention is library-wide, so the escaping must be too."""
    out = normalize_math("Sega sold its stock for $15 million.")

    assert r"\$15 million" in out


def test_an_already_escaped_dollar_is_not_escaped_twice():
    assert normalize_math(r"costs \$5") == r"costs \$5"


def test_emitted_delimiters_are_not_escaped():
    out = normalize_math("  \n    {\\displaystyle x}\n  ")

    assert out == "$$x$$"


def test_a_trailing_control_space_does_not_escape_the_delimiter():
    r"""MediaWiki ends 15 corpus formulas with `\ ` — a TeX control space.

    Stripping it leaves a bare backslash that would escape the `$` we append,
    turning the closing delimiter into a literal dollar.
    """
    out = normalize_math("  \n    {\\displaystyle {\\frac {a}{2}}\\ }\n  ")

    assert out == "$${\\frac {a}{2}}\\ $$"
    assert out.endswith("$$")
