"""Shared test helpers (importlib import mode: test modules cannot import each other)."""

from collections.abc import Callable

import pytest


def _pdf_from_pages(pages: list[str]) -> bytes:
    """Build a small, real PDF whose pages extract (via pypdf) to the given texts.

    Each page uses a Type0/Identity-H font whose ToUnicode CMap maps 2-byte CIDs back to the
    page's characters, so any Unicode text (Korean included) round-trips through text
    extraction without embedding glyphs. Lines are separated with ``T*``.
    """
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog_id = add(b"")  # placeholder, filled after pages are known
    pages_id = add(b"")
    page_ids: list[int] = []
    for text in pages:
        chars = sorted(set(text.replace("\n", "")))
        cid = {ch: i + 1 for i, ch in enumerate(chars)}
        bfchars = "\n".join(
            f"<{cid[ch]:04X}> <{ord(ch):04X}>" if ord(ch) < 0x10000 else "" for ch in chars
        )
        cmap = (
            "/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
            "/CMapName /Custom def\n1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
            + "\n".join(
                f"{len(chunk)} beginbfchar\n" + "\n".join(chunk) + "\nendbfchar"
                for chunk in _chunks(bfchars.splitlines(), 100)
            )
            + "\nendcmap CMapName currentdict /CMap defineresource pop end end"
        ).encode("latin-1")
        tounicode_id = add(
            b"<< /Length " + str(len(cmap)).encode() + b" >>\nstream\n" + cmap + b"\nendstream"
        )
        desc_font_id = add(
            b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /Fake "
            b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
            b"/DW 1000 >>"
        )
        font_id = add(
            b"<< /Type /Font /Subtype /Type0 /BaseFont /Fake /Encoding /Identity-H "
            b"/DescendantFonts [" + str(desc_font_id).encode() + b" 0 R] "
            b"/ToUnicode " + str(tounicode_id).encode() + b" 0 R >>"
        )
        lines = text.split("\n")
        ops = ["BT /F1 10 Tf 12 TL 40 800 Td"]
        for i, line in enumerate(lines):
            hexs = "".join(f"{cid[ch]:04X}" for ch in line)
            if i:
                ops.append("T*")
            ops.append(f"<{hexs}> Tj")
        ops.append("ET")
        content = "\n".join(ops).encode("latin-1")
        content_id = add(
            b"<< /Length "
            + str(len(content)).encode()
            + b" >>\nstream\n"
            + content
            + b"\nendstream"
        )
        page_ids.append(
            add(
                b"<< /Type /Page /Parent " + str(pages_id).encode() + b" 0 R "
                b"/MediaBox [0 0 595 842] /Resources << /Font << /F1 "
                + str(font_id).encode()
                + b" 0 R >> >> /Contents "
                + str(content_id).encode()
                + b" 0 R >>"
            )
        )
    objects[pages_id - 1] = (
        b"<< /Type /Pages /Kids ["
        + b" ".join(f"{p} 0 R".encode() for p in page_ids)
        + b"] /Count "
        + str(len(page_ids)).encode()
        + b" >>"
    )
    objects[catalog_id - 1] = b"<< /Type /Catalog /Pages " + str(pages_id).encode() + b" 0 R >>"

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _chunks(items: list[str], n: int) -> list[list[str]]:
    return [items[i : i + n] for i in range(0, len(items), n)]


@pytest.fixture
def pdf_from_pages() -> Callable[[list[str]], bytes]:
    return _pdf_from_pages
