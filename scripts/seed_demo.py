from __future__ import annotations

import asyncio

from codeflux.config import Settings
from codeflux.storage import Database, WorkflowRepository

TASKS = [
    (
        (
            "Create converter.py with functions to convert length (m, km, mi), weight (g, kg, lb), "
            "and temperature (C, F, K), raising ValueError for unknown units"
        ),
        "gpt-4-tier",
    ),
    (
        "Create cli.py so `python cli.py 10 km mi` prints the converted value using converter.py",
        "gemini-tier",
    ),
    (
        (
            "Create test_converter.py with unittest tests for converter.py and a short README.md "
            "explaining usage and how to run the tests"
        ),
        "gpt-4-tier",
    ),
]


async def main() -> None:
    settings = Settings()
    database = Database(settings.database_url)
    await database.initialize()
    repository = WorkflowRepository(database.sessions)
    workflow_id = await repository.create(
        "Unit converter demo",
        "Build a small, dependency-free Python command-line unit converter. Keep every file in the "
        "workspace root, use only the standard library, and keep the code short and readable.",
        [text for text, _ in TASKS],
    )
    workflow = next(item for item in await repository.list() if item["id"] == workflow_id)
    for item, (_, route) in zip(workflow["items"], TASKS):
        await repository.set_item_model(item["id"], route)
    print(f"WORKFLOW_ID={workflow_id}")
    await database.close()


if __name__ == "__main__":
    asyncio.run(main())
