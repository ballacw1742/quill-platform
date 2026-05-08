"""Seed a dev user with a pre-registered software passkey.

Run with the API venv active:

    .venv/bin/python -m scripts.seed_dev_passkey \\
        --email charles@quill.local --name "Test Mac"

Prints the credential id (base64url) so a test harness can use the
software authenticator at api/tests/_softauthn.py to drive ceremonies.

This is a developer convenience — NOT for production.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys

from sqlalchemy import select

# Make the test helper importable when invoked from repo root.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import db as db_module  # noqa: E402
from app.enums import UserRole  # noqa: E402
from app.models import User, WebAuthnCredential  # noqa: E402
from app.security import hash_password  # noqa: E402
from tests._softauthn import SoftAuthn  # noqa: E402


async def seed(email: str, display_name: str, name: str) -> None:
    async with db_module.SessionLocal() as s:
        res = await s.execute(select(User).where(User.email == email))
        user = res.scalars().first()
        if user is None:
            user = User(
                email=email,
                display_name=display_name,
                role=UserRole.OWNER.value,
                password_hash=hash_password("dev-password-change-me"),
            )
            s.add(user)
            await s.commit()
            await s.refresh(user)
            print(f"created user {user.email} ({user.id})")

        auth = SoftAuthn(rp_id="localhost", origin="http://localhost:3000")
        cred = WebAuthnCredential(
            user_id=user.id,
            credential_id_b64=auth.credential_id_b64url,
            public_key_b64=base64.b64encode(auth.cose_pub_key).decode("ascii"),
            sign_count=0,
            name=name,
            transports="internal,hybrid",
            attachment="platform",
        )
        s.add(cred)
        await s.commit()
        await s.refresh(cred)

        print("--- seeded passkey ---")
        print(f"user_id          : {user.id}")
        print(f"credential id    : {auth.credential_id_b64url}")
        print("private key (PEM): suppress in real life; held in test harness")
        print(f"db row id        : {cred.id}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--email", default="charles@quill.local")
    p.add_argument("--display-name", default="Charles")
    p.add_argument("--name", default="Seeded Test Mac")
    args = p.parse_args()

    asyncio.run(seed(args.email, args.display_name, args.name))


if __name__ == "__main__":
    main()
