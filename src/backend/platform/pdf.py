"""Tiny standard-library PDF writer for synthetic specimen certificates (fakes and seed only).

Produces a valid one-page PDF 1.4 with Helvetica text. Not a document engine: real certificates
are stored exactly as received from the insurer.
"""

from __future__ import annotations

SPECIMEN_BANNER = "SPECIMEN " + chr(0x2013) + " SYNTHETIC DATA"  # en dash, as in the brief
WATERMARK = "SYNTHETIC - NOT A REAL CERTIFICATE"


def _escape(text: str) -> bytes:
    # WinAnsiEncoding covers the en dash (0x96); anything else outside Latin-1 becomes "?".
    raw = text.encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def specimen_pdf(title: str, lines: list[str]) -> bytes:
    """Return PDF bytes with a banner, a title and the given lines."""
    ops = [
        b"BT /F1 20 Tf 0.85 0 0 rg 60 790 Td (" + _escape(SPECIMEN_BANNER) + b") Tj ET",
        b"BT /F1 16 Tf 0 0 0 rg 60 750 Td (" + _escape(title) + b") Tj ET",
    ]
    y = 715
    for line in lines[:40]:
        ops.append(b"BT /F1 11 Tf 60 %d Td (" % y + _escape(line) + b") Tj ET")
        y -= 18
    ops.append(b"BT /F1 26 Tf 0.8 0.8 0.8 rg 1 0 0 1 90 200 Tm (" + _escape(WATERMARK) + b") Tj ET")
    content = b"\n".join(ops)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )
    return bytes(out)
