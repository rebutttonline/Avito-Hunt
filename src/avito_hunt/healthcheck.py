import asyncio
import sys

import asyncpg

from avito_hunt.config import get_settings


async def check() -> None:
    connection = await asyncpg.connect(get_settings().db_url, timeout=5)
    try:
        await connection.fetchval("SELECT 1")
    finally:
        await connection.close()


def main() -> None:
    try:
        asyncio.run(check())
    except Exception as error:
        print(f"unhealthy: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
