"""Infer retrieval facets from the question itself (ADR-0013 §3, the
"hybrid" half the retrieval layer left to "the generation layer").

Two facets matter in practice:

* **Objekt** — "Wann war die letzte ETV im Eibenweg?" asked without the UI's
  property switcher (Siri, a fresh chat) ran org-wide and mostly abstained;
  the ETV/contact roster cards are only forced WITH a property. We match
  street names, object names and the Impower short code (H32) from the
  caller's visible objects against the question.
* **Kontakt / Dienstleister** — proper names embed poorly ("Nummer von
  Weinberger" retrieved other people's contact cards). If the question
  names a contact the index knows (``rag_chunks.contact_name``), retrieval
  is pre-filtered to that name — vendor cards + their invoices.

Both are *hints*: the generation layer retries without an inferred facet
when it yields nothing, so a false positive can't turn an answerable
question into an abstain.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.me import _visible_properties_stmt
from app.models.property import Property
from app.models.user import User
from app.rag.models import RagChunk
from app.rag.retrieval import CallerScope

# Tokens of a contact name that are never the name itself.
_NAME_STOPWORDS = frozenset(
    {
        "gmbh",
        "gbr",
        "kg",
        "ag",
        "ohg",
        "ug",
        "mbh",
        "co",
        "firma",
        "fa",
        "herr",
        "herrn",
        "frau",
        "familie",
        "fam",
        "und",
        "the",
        "e.v.",
        "ev",
        "dr",
        "prof",
        "inhaber",
        "eheleute",
        "erbengemeinschaft",
        "weg",
        "hausverwaltung",
        "verwaltung",
        "service",
        "gesellschaft",
        "sanitär",
        "heizung",
        "elektro",
        "bau",
        "technik",
        "haustechnik",
        "gebäudereinigung",
        "reinigung",
        "hausmeister",
        "hausmeisterservice",
    }
)
_MIN_NAME_TOKEN = 4
_MIN_STREET = 4


@dataclass(frozen=True, slots=True)
class InferredFacets:
    property_id: uuid.UUID | None = None
    contact_query: str | None = None


def fold_street(s: str) -> str:
    """Dictation-tolerant street folding: lower-case, "straße/strasse/str."
    → "str", no spaces/hyphens. "Hasenbergstraße 32" ≈ "Hasenberg Str. 32"."""
    return (
        s.lower()
        .replace("straße", "str")
        .replace("strasse", "str")
        .replace("str.", "str")
        .replace("-", "")
        .replace(" ", "")
    )


def match_property(question: str, props: list[Property]) -> Property | None:
    """The object the question names, or None. Longest street/name match
    wins; the Impower short code (…_H32 → "H32") matches as a whole word."""
    q_folded = fold_street(question)
    best: tuple[Property, int] | None = None
    for p in props:
        candidates: list[str] = []
        if p.street and len(p.street) >= _MIN_STREET:
            candidates.append(fold_street(p.street))
        # Object names carry a type prefix ("WEG Eibenweg 5/7, 71083 …"); the
        # street part alone is what people say — but keep the full folded
        # name too for objects without a street column.
        if p.name:
            candidates.append(fold_street(p.name))
        for key in candidates:
            if len(key) >= 3 and key in q_folded and len(key) > (best[1] if best else 0):
                best = (p, len(key))
        if p.property_hr_id and "_" in p.property_hr_id:
            code = p.property_hr_id.rsplit("_", 1)[-1]
            if len(code) >= 3 and re.search(rf"\b{re.escape(code)}\b", question, re.IGNORECASE):
                score = len(code) + 1  # a spoken code is deliberate — beats short streets
                if score > (best[1] if best else 0):
                    best = (p, score)
    return best[0] if best else None


def match_contact_name(question: str, names: list[str]) -> str | None:
    """The contact/vendor name the question mentions, as the ``ilike``
    fragment to filter ``rag_chunks.contact_name`` by. Matches whole-word
    name tokens (≥ 4 chars, legal-form/salutation tokens ignored); the
    longest token wins, ties → the longer full name (more specific)."""
    best: tuple[str, int, int] | None = None
    for name in names:
        if not name:
            continue
        for raw in re.split(r"[\s,;/&()]+", name):
            token = raw.strip(".-'\"")
            if len(token) < _MIN_NAME_TOKEN or token.lower() in _NAME_STOPWORDS:
                continue
            if not any(ch.isalpha() for ch in token):
                continue
            if re.search(rf"(?<!\w){re.escape(token)}(?!\w)", question, re.IGNORECASE):
                key = (len(token), len(name))
                if best is None or key > (best[1], best[2]):
                    best = (token, len(token), len(name))
    return best[0] if best else None


async def infer_facets(
    app_session: AsyncSession,
    rag_session: AsyncSession,
    *,
    user: User,
    scope: CallerScope,
    question: str,
    property_id: uuid.UUID | None,
    contact_query: str | None,
) -> InferredFacets:
    """Fill the facets the caller did NOT set, from the question. Never
    overrides an explicit property_id/contact (the UI's switcher/facets)."""
    inferred_property: uuid.UUID | None = None
    inferred_contact: str | None = None

    if property_id is None:
        if scope.is_verwalter:
            stmt = select(Property).where(
                Property.organization_id == scope.organization_id,
                Property.deleted_at.is_(None),
            )
        else:
            stmt = _visible_properties_stmt(user)
        props = list((await app_session.scalars(stmt)).all())
        hit = match_property(question, props)
        inferred_property = hit.id if hit else None

    if contact_query is None:
        names_stmt = (
            select(RagChunk.contact_name)
            .where(
                RagChunk.organization_id == scope.organization_id,
                RagChunk.contact_name.is_not(None),
            )
            .distinct()
        )
        if not scope.is_verwalter:
            assert scope.visible_document_ids is not None
            if not scope.visible_document_ids:
                return InferredFacets(property_id=inferred_property)
            names_stmt = names_stmt.where(RagChunk.document_id.in_(scope.visible_document_ids))
        names = [n for n in (await rag_session.scalars(names_stmt)).all() if n]
        inferred_contact = match_contact_name(question, names)

    return InferredFacets(property_id=inferred_property, contact_query=inferred_contact)
