"""
Botragram

Description:
    Entry point for the Botragram application.

Python:
    3.14+
"""

from __future__ import annotations

import asyncio

from botragram.app.application import Application


async def main() -> None:
    """Run the Botragram application."""
    application = Application()
    await application.run()


if __name__ == "__main__":
    asyncio.run(main())
