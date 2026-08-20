r"""Math normalization for scroll bodies — KaTeX delimiters, not token soup.

MediaWiki's `explaintext` extract has no way to render a `<math>` tag, so it
emits the MathML presentation fallback (one symbol per indented line) and then
the real TeX in a `{\displaystyle ...}` wrapper::

      P
      →
      Q
    {\displaystyle P\to Q}

Both halves are content, but only the second half is *readable*. This module
keeps the TeX, drops the fallback, and wraps the result in the `$`/`$$`
delimiters KaTeX and every common Markdown renderer understand. The library's
first full Wikipedia capture landed 8,280 of these across 142 scrolls.

This runs at **render** time, not fetch time. The captured extract stays
verbatim in SQLite — that is what `content_hash` covers and what `verify`
re-checks — so re-rendering a scroll never moves a custody hash, and a better
normalizer later can simply re-render from the store.

Nothing here is Wikipedia-specific: any source whose text carries the same
`{\displaystyle ...}` convention gets the same treatment, and text with no
marker is returned byte-for-byte unchanged.
"""

from __future__ import annotations

import re

# A literal dollar in prose — a price, a shell prompt — would otherwise pair
# with another one and swallow the sentence between them once `$` means math.
# 990 of them are already in the library, 65 in the Nvidia scroll alone.
_BARE_DOLLAR = re.compile(r"(?<!\\)\$")

# The TeX wrapper MediaWiki emits. `\textstyle` appears where the formula sat
# inline in the source; both are unwrapped, because the delimiter we choose
# (`$` vs `$$`) already carries that distinction to the renderer.
_MARKER = re.compile(r"\{\\(?:displaystyle|textstyle)\s")


def normalize_math(text: str) -> str:
    """Replace MathML-fallback math blocks with KaTeX `$`/`$$` delimiters.

    Args:
        text: Scroll body text, possibly containing `{\\displaystyle ...}`
            blocks preceded by their MathML token fallback.

    Returns:
        The text with each math block collapsed to `$tex$` when the formula sat
        inside a sentence, or a standalone `$$tex$$` paragraph when it did not.
        Literal dollars in prose are escaped to `\\$` throughout, so the only
        live delimiters in the result are the ones this function emitted.
    """
    if not text:
        return text
    if not _MARKER.search(text):
        return _BARE_DOLLAR.sub(r"\\$", text)

    # Escape first, so the only unescaped dollars left are the ones we emit.
    lines = _BARE_DOLLAR.sub(r"\\$", text).split("\n")
    out: list[str] = []
    merge_next = False
    index = 0

    while index < len(lines):
        block = _read_block(lines, index)
        if block is None:
            line = lines[index]
            if merge_next and line.strip():
                out[-1] += line
            else:
                out.append(line)
            merge_next = False
            index += 1
            continue

        tex, index = block
        # The fallback tokens precede the marker, so they are already emitted.
        while out and _is_fallback(out[-1]):
            out.pop()

        if out and out[-1].strip():  # the formula sat mid-sentence
            out[-1] += f"${tex}$"
            merge_next = True
        else:
            out.append(f"$${tex}$$")
            merge_next = False

    return "\n".join(out)


def _read_block(lines: list[str], index: int) -> tuple[str, int] | None:
    """Read the math block starting at `index`, if one starts there.

    Args:
        lines: The body split on newlines.
        index: Candidate start line.

    Returns:
        A `(tex, next_index)` pair, or None when `lines[index]` is not the
        marker line of a math block.
    """
    line = lines[index]
    match = _MARKER.search(line)
    if match is None or line[: match.start()].strip():
        return None  # a marker with prose before it is not a fallback block

    end = _match_brace(line, match.start())
    if end is None:
        return None  # unterminated wrapper: leave the text alone

    tex = line[match.end() : end].strip()
    # A formula may legitimately end in `\ ` (a TeX control space). Stripping
    # that space bares the backslash, which would then escape the `$` we append
    # and silently turn the closing delimiter into a literal dollar.
    if (len(tex) - len(tex.rstrip("\\"))) % 2:
        tex += " "
    index += 1
    while index < len(lines) and _is_fallback(lines[index]):
        index += 1
    return tex, index


def _match_brace(line: str, start: int) -> int | None:
    """Find the `}` closing the group opened at `start`.

    Args:
        line: The line holding the wrapper.
        start: Index of the opening `{`.

    Returns:
        Index of the matching `}`, or None if the group never closes.

    A backslash escapes the next character, so the literal braces in
    `\\left\\{` do not count toward the depth.
    """
    depth = 0
    escaped = False
    for offset in range(start, len(line)):
        char = line[offset]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return offset
    return None


def _is_fallback(line: str) -> bool:
    """Report whether a line is MathML-fallback noise rather than content.

    Args:
        line: A single body line.

    Returns:
        True for the indented single-symbol lines and the whitespace-only
        spacer lines that make up the fallback.

    This is a shape heuristic, and deliberately a narrow one: it is consulted
    only for lines directly adjacent to a `{\\displaystyle}` marker, so
    genuinely indented prose elsewhere in a body is never considered. A truly
    empty line is not fallback — it is the paragraph break that tells display
    math apart from inline.
    """
    return line != "" and (not line.strip() or line.startswith("  "))
