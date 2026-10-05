from codeflux.storage import Database, WorkflowRepository


async def test_workflow_progress_persists():
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    repository = WorkflowRepository(database.sessions)
    workflow_id = await repository.create("Demo", "Build the demo", ["Plan", "Test"], "gpt-4-tier")
    workflows = await repository.list()
    await repository.set_item(workflows[0]["items"][0]["id"], True)
    await repository.add_item(workflow_id, "Present", "gemini-tier")
    await repository.set_item_model(workflows[0]["items"][1]["id"], "gemini-tier")
    await repository.save_result(workflow_id, "Done")
    saved = (await repository.list())[0]
    assert saved["status"] == "completed"
    assert saved["result"] == "Done"
    assert [item["completed"] for item in saved["items"]] == [True, False, False]
    assert [item["model_route"] for item in saved["items"]] == [
        "gpt-4-tier",
        "gemini-tier",
        "gemini-tier",
    ]
    handoff = await repository.next_ide_task(workflow_id)
    assert handoff is not None
    assert handoff["task"] == "Test"
    assert handoff["model"] == "gemini-tier"
    assert "MASTER REQUEST" in handoff["messages"][1]["content"]
    completed = await repository.complete_ide_task(workflow_id, handoff["task_id"], "Tests pass")
    assert completed["workflow_status"] == "in_progress"
    await repository.delete_item(saved["items"][0]["id"])
    after_item_deleted = (await repository.list())[0]
    assert len(after_item_deleted["items"]) == 2
    await repository.delete(workflow_id)
    assert len(await repository.list()) == 0
    await database.close()
