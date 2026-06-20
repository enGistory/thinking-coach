from __future__ import annotations

import asyncio


async def run_worker() -> None:
    await asyncio.Event().wait()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
