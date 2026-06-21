from __future__ import annotations

import argparse
import asyncio
import getpass
import os

from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.db.session import dispose_engine, get_sessionmaker
from app.repositories.auth import UserRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the first local ADMIN account.")
    parser.add_argument("--nickname", required=True)
    parser.add_argument(
        "--password-env",
        help="Read the initial password from this environment variable instead of prompting.",
    )
    return parser.parse_args()


async def create_admin(nickname: str, password: str) -> None:
    async with get_sessionmaker()() as session:
        repository = UserRepository(session)
        if await repository.has_admin():
            raise RuntimeError("An ADMIN account already exists")
        if await repository.get_by_nickname(nickname) is not None:
            raise RuntimeError("Nickname already exists")
        await repository.create_user(
            nickname=nickname,
            password_hash=hash_password(password),
            role="ADMIN",
        )
        await session.commit()


async def async_main() -> int:
    args = parse_args()
    nickname = args.nickname.strip()
    try:
        if not nickname:
            raise RuntimeError("Nickname must not be empty")
        password = _read_password(args.password_env)
        await create_admin(nickname, password)
    except (IntegrityError, RuntimeError) as exc:
        print(f"Failed to create ADMIN: {exc}")
        return 1
    finally:
        await dispose_engine()
    print(f"Created ADMIN account: {nickname}")
    return 0


def _read_password(password_env: str | None) -> str:
    if password_env:
        password = os.getenv(password_env, "")
    else:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            raise RuntimeError("Passwords do not match")
    if len(password) < 8:
        raise RuntimeError("Password must be at least 8 characters")
    return password


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
