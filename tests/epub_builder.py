"""Builds minimal in-memory EPUBs for tests. Not a test module itself (no
`test_` prefix, so pytest does not collect it) — a fixture-construction
helper shared by the pure parser tests and the DB-backed ingestion tests.
"""

from __future__ import annotations

import io
import zipfile

DEFAULT_CHAPTERS = [
    "<html><body><h1>Chapter One</h1><p>It was a dark and stormy night.</p></body></html>",
    "<html><body><h1>Chapter Two</h1><p>The next morning brought clarity.</p></body></html>",
]


def build_epub(
    *,
    title: str | None = "Test Book",
    author: str | None = "Test Author",
    chapter_htmls: list[str] | None = None,
    non_linear_indices: frozenset[int] = frozenset(),
    include_container: bool = True,
) -> bytes:
    chapters = DEFAULT_CHAPTERS if chapter_htmls is None else chapter_htmls

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        if include_container:
            zf.writestr(
                "META-INF/container.xml",
                '<?xml version="1.0"?>'
                '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                'media-type="application/oebps-package+xml"/></rootfiles></container>',
            )

        manifest_items = []
        spine_items = []
        for i, html in enumerate(chapters, start=1):
            href = f"chapter{i}.xhtml"
            zf.writestr(f"OEBPS/{href}", html)
            manifest_items.append(
                f'<item id="chap{i}" href="{href}" media-type="application/xhtml+xml"/>'
            )
            linear_attr = ' linear="no"' if i in non_linear_indices else ""
            spine_items.append(f'<itemref idref="chap{i}"{linear_attr}/>')

        title_el = f"<dc:title>{title}</dc:title>" if title else ""
        author_el = f"<dc:creator>{author}</dc:creator>" if author else ""
        opf = (
            '<?xml version="1.0"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="2.0">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"{title_el}{author_el}"
            "</metadata>"
            f"<manifest>{''.join(manifest_items)}</manifest>"
            f"<spine>{''.join(spine_items)}</spine>"
            "</package>"
        )
        zf.writestr("OEBPS/content.opf", opf)

    return buf.getvalue()
