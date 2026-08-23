"""Facet inference from the question (app/rag/query_facets.py): which object
and which contact a question names, and that answer_question scopes
retrieval with them — with a fallback when the inferred facet finds nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import get_settings
from app.models.document import DocumentKind
from app.models.property import Property
from app.models.user import UserRole
from app.rag.constants import EMBEDDING_DIM
from app.rag.generation import answer_question
from app.rag.models import RagChunk
from app.rag.query_facets import fold_street, match_contact_name, match_property
from app.tests._factories import make_document, make_org, make_property, make_user

_VEC = [0.1] * EMBEDDING_DIM


def _prop(name: str, street: str | None, hr: str | None = None) -> Property:
    return Property(id=uuid.uuid4(), name=name, street=street, property_hr_id=hr)


# --- pure matching ---------------------------------------------------------


def test_fold_street_tolerates_dictation_variants() -> None:
    assert fold_street("Hasenbergstraße 32") == fold_street("Hasenberg Str. 32")
    assert fold_street("Hasenbergstrasse") == "hasenbergstr"


def test_match_property_by_street_name_in_question() -> None:
    eiben = _prop("WEG Eibenweg 5/7, 71083 Herrenberg", "Eibenweg", "Herrenberg_E5")
    fried = _prop("WEG Friedrichstraße 33, 71638 Ludwigsburg", "Friedrichstraße", "Ludwigsburg_F33")
    hit = match_property("Wann war die letzte ETV im Eibenweg?", [fried, eiben])
    assert hit is eiben


def test_match_property_longest_street_wins_and_short_code_matches_as_word() -> None:
    hasen = _prop("WEG Hasenbergstraße 32", "Hasenbergstraße", "Stuttgart_H32")
    berg = _prop("MV Bergstraße 1", "Bergstraße", "Stuttgart_B1")
    # "Hasenbergstraße" contains "bergstr" — the longer, more specific street wins
    assert match_property("Heizung in der Hasenbergstraße", [berg, hasen]) is hasen
    # spoken short code
    assert match_property("Was ist bei H32 offen?", [berg, hasen]) is hasen
    # "h32" inside another token is NOT a code match
    assert match_property("Rechnung RH3210 bitte", [berg, hasen]) is None


def test_match_property_none_when_nothing_named() -> None:
    p = _prop("WEG Eibenweg 5/7", "Eibenweg")
    assert match_property("Wann ist die nächste Versammlung?", [p]) is None


def test_match_contact_name_picks_vendor_token_and_ignores_legal_forms() -> None:
    names = ["Weinberger", "Müller GmbH", "Familie Yilmaz", "EnBW Energie Baden-Württemberg AG"]
    assert match_contact_name("Nummer von Herrn Weinberger im Eibenweg", names) == "Weinberger"
    assert match_contact_name("Was hat Yilmaz gezahlt?", names) == "Yilmaz"
    # legal-form tokens never match on their own
    assert match_contact_name("Welche GmbH hat die Heizung gemacht?", names) is None
    # whole-word only: "Weinberg" ≠ "Weinberger"
    assert match_contact_name("Der Weinberg ist schön", names) is None
    # nothing named → None
    assert match_contact_name("Wann war die letzte ETV?", names) is None


# --- end to end --------------------------------------------------------------


class _FakeProvider:
    def __init__(self) -> None:
        self.generate_called = False

    async def embed_texts(
        self, texts: Sequence[str], *, task_type: str = "retrieval_document"
    ) -> list[list[float]]:
        return [list(_VEC) for _ in texts]

    async def generate(self, *, prompt: str, system: str | None = None, **_: object) -> str:
        self.generate_called = True
        return "Antwort [1]."


async def test_answer_question_infers_object_and_contact_from_question(
    test_engine: AsyncEngine, session: AsyncSession, rag_session: AsyncSession
) -> None:
    org = await make_org(test_engine)
    eiben = await make_property(test_engine, org=org, name="WEG Eibenweg 5/7, 71083 Herrenberg")
    fried = await make_property(
        test_engine, org=org, name="WEG Friedrichstraße 33, 71638 Ludwigsburg"
    )
    # streets live on the model, the factory doesn't set them
    async with session.begin():
        for p, street in ((eiben, "Eibenweg"), (fried, "Friedrichstraße")):
            row = await session.get(Property, p.id)
            assert row is not None
            row.street = street
    doc_e = await make_document(test_engine, org=org, prop=eiben, kind=DocumentKind.RECHNUNG)
    doc_f = await make_document(test_engine, org=org, prop=fried, kind=DocumentKind.RECHNUNG)
    rag_session.add_all(
        [
            RagChunk(
                document_id=doc_e.id,
                organization_id=org.id,
                property_id=eiben.id,
                visibility="ALL",
                chunk_text="Rechnung Weinberger Sanitär, Telefon 07032 6317, Eibenweg.",
                contact_name="Weinberger",
                embedding=_VEC,
            ),
            RagChunk(
                document_id=doc_f.id,
                organization_id=org.id,
                property_id=fried.id,
                visibility="ALL",
                chunk_text="Einladung zur Eigentümerversammlung Friedrichstraße.",
                contact_name="Hausverwaltung Wagner",
                embedding=_VEC,
            ),
        ]
    )
    await rag_session.flush()
    verwalter, _e, _p = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    provider = _FakeProvider()

    # object + vendor named → only the Eibenweg/Weinberger chunk is retrieved
    answer = await answer_question(
        session,
        rag_session,
        user=verwalter,
        question="Nummer von Herrn Weinberger im Eibenweg?",
        embedder=provider,
        generator=provider,
        settings=get_settings(),
    )
    assert not answer.abstained
    assert answer.property_id == eiben.id
    assert answer.contact_query == "Weinberger"
    assert answer.retrieved_document_ids == [doc_e.id]

    # object named, no contact → property scope only
    answer = await answer_question(
        session,
        rag_session,
        user=verwalter,
        question="Was gibt es Neues in der Friedrichstraße?",
        embedder=provider,
        generator=provider,
        settings=get_settings(),
    )
    assert answer.property_id == fried.id
    assert answer.contact_query is None
    assert answer.retrieved_document_ids == [doc_f.id]

    # inferred vendor with no chunks under the (also inferred) object →
    # fallback drops the contact filter, then the object: still answers
    answer = await answer_question(
        session,
        rag_session,
        user=verwalter,
        question="Hat Weinberger in der Friedrichstraße gearbeitet?",
        embedder=provider,
        generator=provider,
        settings=get_settings(),
    )
    assert not answer.abstained
    # contact filter dropped (no Weinberger chunk on Friedrichstraße), object kept
    assert answer.contact_query is None
    assert answer.property_id == fried.id
    assert answer.retrieved_document_ids == [doc_f.id]


async def test_explicit_property_is_never_overridden_by_inference(
    test_engine: AsyncEngine, session: AsyncSession, rag_session: AsyncSession
) -> None:
    org = await make_org(test_engine)
    a = await make_property(test_engine, org=org, name="WEG Eibenweg 5/7")
    b = await make_property(test_engine, org=org, name="WEG Friedrichstraße 33")
    async with session.begin():
        for p, street in ((a, "Eibenweg"), (b, "Friedrichstraße")):
            row = await session.get(Property, p.id)
            assert row is not None
            row.street = street
    doc_b = await make_document(test_engine, org=org, prop=b, kind=DocumentKind.RECHNUNG)
    rag_session.add(
        RagChunk(
            document_id=doc_b.id,
            organization_id=org.id,
            property_id=b.id,
            visibility="ALL",
            chunk_text="Friedrichstraße Protokoll.",
            embedding=_VEC,
        )
    )
    await rag_session.flush()
    verwalter, _e, _p = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    provider = _FakeProvider()

    # the UI's switcher says B although the question names A → B stays
    answer = await answer_question(
        session,
        rag_session,
        user=verwalter,
        question="Gibt es etwas zum Eibenweg?",
        embedder=provider,
        generator=provider,
        settings=get_settings(),
        property_id=b.id,
    )
    assert answer.property_id == b.id
    assert answer.retrieved_document_ids == [doc_b.id]
