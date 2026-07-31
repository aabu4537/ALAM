"""EPUB container parsing — proposes a chapter structure from spine order.

Per ADR-0004, spine order is a hypothesis, not the answer: this module's job
is a reasonable first guess for a human to correct during verification, not a
perfect result. Malformed chapter markup degrades to a coarser guess rather
than failing the whole ingestion.

Operates only on the bytes it is given (an in-memory zip) — no filesystem or
network access. Parsing structured bytes into structured data is computation,
not I/O, which is why this can be tested without fixtures or mocks even
though it lives under `media/books/` rather than `domain/` (ADR-0003 places
book-specific mechanics here).
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

if TYPE_CHECKING:
    from collections.abc import Mapping

CONTAINER_PATH = "META-INF/container.xml"
CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
OPF_NS = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}

FIRST_LINES_MAX_CHARS = 240
LABEL_MAX_CHARS = 200


class EpubParseError(ValueError):
    """The file is not a readable EPUB container."""


@dataclass(frozen=True, slots=True)
class EpubMetadata:
    title: str | None
    author: str | None


@dataclass(frozen=True, slots=True)
class ProposedUnit:
    ordinal: int
    label: str
    first_lines: str | None


@dataclass(frozen=True, slots=True)
class ParsedEpub:
    metadata: EpubMetadata
    units: tuple[ProposedUnit, ...]


def parse_epub(data: bytes) -> ParsedEpub:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise EpubParseError("not a valid EPUB (not a zip container)") from exc

    opf_path = _find_opf_path(archive)
    opf_root = _read_xml(archive, opf_path)
    opf_dir = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""

    metadata = _read_metadata(opf_root)
    manifest = _read_manifest(opf_root)
    spine_hrefs = _read_spine(opf_root, manifest)
    if not spine_hrefs:
        raise EpubParseError("EPUB spine is empty — nothing to propose a structure from")

    units = []
    for ordinal, href in enumerate(spine_hrefs, start=1):
        heading, text = _read_content(archive, opf_dir + href)
        label = heading[:LABEL_MAX_CHARS] if heading else f"Chapter {ordinal}"
        units.append(ProposedUnit(ordinal=ordinal, label=label, first_lines=_first_lines(text)))

    return ParsedEpub(metadata=metadata, units=tuple(units))


def _find_opf_path(archive: zipfile.ZipFile) -> str:
    try:
        raw = archive.read(CONTAINER_PATH)
    except KeyError as exc:
        raise EpubParseError(f"missing {CONTAINER_PATH} — not an EPUB container") from exc
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise EpubParseError(f"{CONTAINER_PATH} is not valid XML") from exc
    rootfile = root.find(".//c:rootfile", CONTAINER_NS)
    if rootfile is None or "full-path" not in rootfile.attrib:
        raise EpubParseError(f"{CONTAINER_PATH} has no rootfile entry")
    return rootfile.attrib["full-path"]


def _read_xml(archive: zipfile.ZipFile, path: str) -> ET.Element:
    try:
        raw = archive.read(path)
    except KeyError as exc:
        raise EpubParseError(f"referenced file is missing from the archive: {path}") from exc
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise EpubParseError(f"{path} is not valid XML") from exc


def _read_metadata(opf_root: ET.Element) -> EpubMetadata:
    return EpubMetadata(
        title=_text_or_none(opf_root.find(".//dc:title", OPF_NS)),
        author=_text_or_none(opf_root.find(".//dc:creator", OPF_NS)),
    )


def _text_or_none(el: ET.Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    return el.text.strip() or None


def _read_manifest(opf_root: ET.Element) -> Mapping[str, str]:
    manifest = {}
    for item in opf_root.findall(".//opf:manifest/opf:item", OPF_NS):
        item_id, href = item.attrib.get("id"), item.attrib.get("href")
        if item_id and href:
            manifest[item_id] = href
    if not manifest:
        raise EpubParseError("OPF manifest is empty")
    return manifest


def _read_spine(opf_root: ET.Element, manifest: Mapping[str, str]) -> list[str]:
    hrefs = []
    for itemref in opf_root.findall(".//opf:spine/opf:itemref", OPF_NS):
        if itemref.attrib.get("linear") == "no":
            continue
        idref = itemref.attrib.get("idref")
        href = manifest.get(idref) if idref else None
        if href:
            hrefs.append(href)
    return hrefs


_TAG_RE = re.compile(r"<[^>]+>")
_HEADING_RE = re.compile(r"<h[1-3][^>]*>(.*?)</h[1-3]>", re.IGNORECASE | re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")


def _read_content(archive: zipfile.ZipFile, path: str) -> tuple[str, str]:
    """Returns ``(heading_guess, plain_text)``.

    Deliberately a regex strip rather than an XML parse — real-world EPUB
    chapter markup is often not strictly well-formed, and a chapter that fails
    to parse should degrade to a plain "Chapter N" guess, not abort the whole
    ingestion.
    """
    try:
        raw = archive.read(path)
    except KeyError:
        return "", ""
    html = raw.decode("utf-8", errors="replace")

    heading = ""
    match = _HEADING_RE.search(html)
    if match:
        heading = _clean_text(match.group(1))

    return heading, _clean_text(html)


def _clean_text(html: str) -> str:
    return _WHITESPACE_RE.sub(" ", _TAG_RE.sub(" ", html)).strip()


def _first_lines(text: str) -> str | None:
    return text[:FIRST_LINES_MAX_CHARS] or None
