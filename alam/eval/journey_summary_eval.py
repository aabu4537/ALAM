"""Adversarial case for ``GET /books/{id}/journey-summary`` (M6 session 1,
ADR-0002 Layer 3, ADR-0013) — ``synthesis_leakage_rate``, M6's headline
number.

Complements ``alam/eval/spoiler_eval.py`` (memories),
``.../prediction_spoiler_eval.py`` (predictions), and
``.../structure_spoiler_eval.py`` (chapters/structure) — this is the first
surface that *generates* prose rather than retrieving existing records, so
it is the first case that actually exercises Layer 3
(``ai/synthesis/leak_check.py``) rather than Layer 1 alone.

**Not a real quality signal while ``ALAM_LLM_PROVIDER=fake``** — same
caveat ``extraction_eval.py`` documents. ``FakeLLM`` has no real judgment;
this harness supplies a canned, schema-valid narrative and a canned, clean
Layer 3 verdict so the plumbing (seeding, ordinal exclusion, prompt
assembly, the persisted row, the endpoint's response) is exercised end to
end. ``distinctive_language_not_in_draft`` is real regardless of which
provider is behind ``FakeLLM``, though: it is a plain substring check on the
draft actually persisted and returned, defense-in-depth on the Layer 3
verdict itself — even a compromised or misconfigured Layer 3 canned
response could not silently mask spoiler text making it all the way into a
served draft.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from fastapi.testclient import TestClient

from alam.ai.extraction.memories import ExtractedMemory
from alam.ai.extraction.memories import MemoryType as ExtractedMemoryType
from alam.ai.providers.fakes import FakeLLM
from alam.api.dependencies import require_owner_session
from alam.api.main import create_app
from alam.eval.models import SpoilerCaseResult, SpoilerEvalReport
from alam.persistence.repositories import (
    CaptureRepository,
    JourneySummaryRepository,
    MediaItemRepository,
    MemoryRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)
from alam.persistence.session import session_scope

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session

    from alam.persistence.models import MediaItem

_DISTINCTIVE_SPOILER_PHRASE = "the emperor abdicates the throne to Paul at the novel's end"
_CLEAN_NARRATIVE = (
    '{"narrative": "The reader has been captivated by the opening chapters '
    "on Arrakis and is forming early theories about the political intrigue "
    'at court."}'
)
_CLEAN_LEAK_VERDICT = '{"leaked": false, "spans": []}'


def _memory_at(session: Session, book: MediaItem, *, ordinal: int, content: str) -> None:
    unit = StructureUnitRepository(session).create(
        media_item_id=book.id, ordinal=ordinal, label=f"Chapter {ordinal}"
    )
    reading_session = ReadingSessionRepository(session).get_or_create_active(
        book.id, structure_unit_id=unit.id, ordinal=ordinal, progress=1.0
    )
    capture = CaptureRepository(session).create(
        reading_session_id=reading_session.id,
        media_item_id=book.id,
        structure_unit_id=unit.id,
        structure_ordinal=ordinal,
        audio_data=b"x",
    )
    MemoryRepository(session).create_many(
        capture_id=capture.id,
        media_item_id=book.id,
        structure_unit_id=unit.id,
        structure_ordinal=ordinal,
        prompt_version_id="extract-memories-v1",
        extracted=[ExtractedMemory(memory_type=ExtractedMemoryType.OPINION, content=content)],
    )


def run_journey_summary_spoiler_eval(session: Session) -> SpoilerEvalReport:
    """One book, a visible memory at ordinal 1, a spoiler-shaped memory at
    ordinal 9 (a major reveal, excluded by the ordinal filter once the
    active session is repositioned to ordinal 3 — mid-book, well short of
    the reveal). Generates a journey summary through the real endpoint and
    checks:

    - ``layer3_verdict_clean``: the persisted Layer 3 result is
      ``leaked=False`` — the canned verdict this harness supplies, real
      only once a real LLM provider backs Layer 3 (see the module
      docstring).
    - ``distinctive_language_not_in_draft``: defense-in-depth on the check
      above — the spoiler memory's own distinctive phrase must not appear
      verbatim in the draft actually returned, regardless of what Layer 3
      said.
    """
    owner = UserRepository(session).create(display_name="Eval Owner")
    book = MediaItemRepository(session).create(user_id=owner.id, title="Eval Book")

    _memory_at(session, book, ordinal=1, content="I loved the opening chapters on Arrakis")
    _memory_at(session, book, ordinal=9, content=_DISTINCTIVE_SPOILER_PHRASE)

    # Repositioned explicitly rather than trusting whatever ordinal the last
    # seed left the session at — same idiom `structure_spoiler_eval` uses.
    reposition_unit = StructureUnitRepository(session).create(
        media_item_id=book.id, ordinal=3, label="Chapter 3"
    )
    ReadingSessionRepository(session).get_or_create_active(
        book.id, structure_unit_id=reposition_unit.id, ordinal=3, progress=0.3
    )

    fake_llm = FakeLLM(responses=[_CLEAN_NARRATIVE, _CLEAN_LEAK_VERDICT])

    def _session_override() -> Iterator[Session]:
        yield session

    app = create_app()
    app.dependency_overrides[session_scope] = _session_override
    app.dependency_overrides[require_owner_session] = lambda: None
    try:
        with (
            patch("alam.services.journey_summary.get_llm_provider", return_value=fake_llm),
            TestClient(app) as client,
        ):
            response = client.get(f"/books/{book.id}/journey-summary")
            response.raise_for_status()
            draft = response.json()["narrative"]
    finally:
        app.dependency_overrides.clear()

    row = JourneySummaryRepository(session).get_latest_for_media_item(book.id)
    if row is None:
        raise AssertionError("generation reported success but persisted no row — a setup bug")

    layer3_leaked = bool(row.layer3_leaked)
    distinctive_language_leaked = _DISTINCTIVE_SPOILER_PHRASE in draft

    results = (
        SpoilerCaseResult(
            label="layer3_verdict_clean",
            leaked=layer3_leaked,
            leaked_labels=("layer3_leaked",) if layer3_leaked else (),
        ),
        SpoilerCaseResult(
            label="distinctive_language_not_in_draft",
            leaked=distinctive_language_leaked,
            leaked_labels=("spoiler_memory",) if distinctive_language_leaked else (),
        ),
    )

    leakage_rate = sum(1 for r in results if r.leaked) / len(results)
    return SpoilerEvalReport(leakage_rate=leakage_rate, results=results)
