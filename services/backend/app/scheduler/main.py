from __future__ import annotations

import asyncio


async def run_scheduler() -> None:
    await asyncio.Event().wait()


def main() -> None:
    asyncio.run(run_scheduler())


if __name__ == "__main__":
    main()
