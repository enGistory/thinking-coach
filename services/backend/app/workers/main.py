from __future__ import annotations

import asyncio

from app.core.config import get_settings


async def run_worker() -> None:
    get_settings().validate_ai()
    await asyncio.Event().wait()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
