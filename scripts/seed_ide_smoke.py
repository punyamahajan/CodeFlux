from __future__ import annotations

import asyncio

from codeflux.config import Settings
from codeflux.storage import Database, WorkflowRepository


async def main() -> None:
    settings = Settings()
    database = Database(settings.database_url)
    await database.initialize()
    repository = WorkflowRepository(database.sessions)
    workflow_id = await repository.create(
        "CodeFlux IDE smoke project",
        (
            "Build a small, dependency-free Python command-line task tracker inside the "
            "codeflux-ide-smoke folder. It must support adding and listing tasks, persist data "
            "as JSON, include automated tests, and include a concise README. Do not modify files "
            "outside that folder."
        ),
        [
            "Implement the task tracker package and command-line interface",
            "Add automated tests and usage documentation",
        ],
        "gpt-4-tier",
    )
    workflows = await repository.list()
    workflow = next(item for item in workflows if item["id"] == workflow_id)
    await repository.set_item_model(workflow["items"][1]["id"], "gemini-tier")
    print(
        f"WORKFLOW_ID={workflow_id} TASKS={len(workflow['items'])} "
        "ROUTES=gpt-4-tier,gemini-tier"
    )
    await database.close()


if __name__ == "__main__":
    asyncio.run(main())
