"""Shared minimal-PDF builder for adapter tests.

Builds a tiny one-page PDF carrying `text` in its content stream, plus an
optional document-information dictionary, so adapter tests can exercise
pypdf extraction offline without committing binary fixture files.
"""

from __future__ import annotations


def make_pdf(text: str, info: dict[str, str] | None = None) -> bytes:
    """A minimal one-page PDF carrying `text`, with optional /Info metadata.

    `info` maps PDF info keys ("Title", "Author", "Subject",
    "CreationDate") to plain ASCII values containing no parentheses.
    """
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    trailer_info = b""
    if info:
        entries = "".join(f" /{key} ({value})" for key, value in info.items())
        objects.append(b"<<%s >>" % entries.encode("ascii"))
        trailer_info = b" /Info %d 0 R" % len(objects)
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R%s >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        trailer_info,
        xref_at,
    )
    return bytes(out)
