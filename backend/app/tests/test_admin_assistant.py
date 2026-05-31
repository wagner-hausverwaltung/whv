"""Admin assistant conversation overview (ADR-0013): the list groups turns by
conversation_id; the detail returns a thread in chronological order. App-DB
only — no RAG store needed."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.v1.admin_assistant import get_conversation, list_conversations
from app.models import AssistantMessage
from app.models.user import UserRole
from app.tests._factories import make_org, make_user


async def test_admin_assistant_list_and_detail(
    test_engine: AsyncEngine, session: AsyncSession
) -> None:
    org = await make_org(test_engine)
    verwalter, _e, _p = await make_user(test_engine, org=org, role=UserRole.VERWALTER)

    conv = uuid.uuid4()
    base = datetime.now(UTC)
    session.add_all(
        [
            AssistantMessage(
                organization_id=org.id,
                conversation_id=conv,
                actor_user_id=verwalter.id,
                property_id=None,
                question="Erste Frage?",
                answer="Antwort 1 [1].",
                abstained=False,
                citations=[
                    {
                        "index": 1,
                        "document_id": str(uuid.uuid4()),
                        "page": 3,
                        "source_kind": "RECHNUNG",
                        "source_type": "document",
                        "contact_name": None,
                    }
                ],
                retrieved_document_ids=[],
                created_at=base,
            ),
            AssistantMessage(
                organization_id=org.id,
                conversation_id=conv,
                actor_user_id=verwalter.id,
                property_id=None,
                question="Folgefrage?",
                answer="Antwort 2.",
                abstained=False,
                citations=[],
                retrieved_document_ids=[],
                created_at=base + timedelta(minutes=1),
            ),
            AssistantMessage(
                organization_id=org.id,
                conversation_id=uuid.uuid4(),
                actor_user_id=verwalter.id,
                property_id=None,
                question="Andere Konversation?",
                answer="Dazu habe ich nichts gefunden.",
                abstained=True,
                citations=[],
                retrieved_document_ids=[],
                created_at=base + timedelta(minutes=2),
            ),
        ]
    )
    await session.flush()

    listing = await list_conversations(
        current_user=verwalter, session=session, limit=50, offset=0, user_id=None, property_id=None
    )
    assert len(listing.items) == 2  # the 2-turn thread + the standalone
    by_id = {c.conversation_id: c for c in listing.items}
    assert by_id[conv].message_count == 2
    assert by_id[conv].first_question == "Erste Frage?"
    assert by_id[conv].user_email == verwalter.email
    # newest conversation first
    assert listing.items[0].conversation_id != conv

    detail = await get_conversation(conversation_id=conv, current_user=verwalter, session=session)
    assert [m.question for m in detail.messages] == ["Erste Frage?", "Folgefrage?"]
    assert detail.messages[0].citations[0].index == 1
    assert detail.messages[0].citations[0].source_kind == "RECHNUNG"
