import argparse
import asyncio
import secrets
import string
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.constants import WHV_ORGANIZATION_ID
from app.models import InviteCode, UserRole

# Excludes visually ambiguous characters (0/O, 1/I/L).
_INVITE_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1IL")


def generate_invite_code(length: int = 8) -> str:
    return "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(length))


async def create_invite(
    email: str,
    role: UserRole,
    contact_id_impower: int | None,
    ttl_days: int,
) -> tuple[str, datetime]:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    code = generate_invite_code()
    expires_at = datetime.now(UTC) + timedelta(days=ttl_days)

    async with session_factory() as session:
        session.add(
            InviteCode(
                organization_id=WHV_ORGANIZATION_ID,
                code=code,
                email=email.lower(),
                role=role,
                contact_id_impower=contact_id_impower,
                expires_at=expires_at,
            )
        )
        await session.commit()

    await engine.dispose()
    return code, expires_at


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.auth.bootstrap")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ci = sub.add_parser("create-invite", help="Create a single-use invite code for the WHV org.")
    ci.add_argument("email")
    ci.add_argument("--role", choices=[r.value for r in UserRole], required=True)
    ci.add_argument("--contact-id-impower", type=int, default=None)
    ci.add_argument("--ttl-days", type=int, default=14)
    args = parser.parse_args()

    code, expires_at = asyncio.run(
        create_invite(
            email=args.email,
            role=UserRole(args.role),
            contact_id_impower=args.contact_id_impower,
            ttl_days=args.ttl_days,
        )
    )
    print(f"\n  invite code:  {code}")
    print(f"  email:        {args.email}")
    print(f"  role:         {args.role}")
    contact = args.contact_id_impower if args.contact_id_impower is not None else "(none)"
    print(f"  contact_id:   {contact}")
    print(f"  expires:      {expires_at.isoformat()}\n")
    print("Redeem with:")
    print("  curl -X POST http://localhost:8000/auth/invite/redeem \\")
    print("    -H 'Content-Type: application/json' \\")
    body = f'{{"code":"{code}","email":"{args.email}","password":"<choose-a-strong-password>"}}'
    print(f"    -d '{body}'\n")


if __name__ == "__main__":
    main()
