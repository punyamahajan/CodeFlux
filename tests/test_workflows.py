from codeflux.storage import Database, WorkflowRepository


async def test_workflow_progress_persists():
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    repository = WorkflowRepository(database.sessions)
    workflow_id = await repository.create("Demo", "Build the demo", ["Plan", "Test"])
    workflows = await repository.list()
    await repository.set_item(workflows[0]["items"][0]["id"], True)
    await repository.add_item(workflow_id, "Present")
    await repository.save_result(workflow_id, "Done")
    saved = (await repository.list())[0]
    assert saved["status"] == "completed"
    assert saved["result"] == "Done"
    assert [item["completed"] for item in saved["items"]] == [True, False, False]
    await repository.delete_item(saved["items"][0]["id"])
    after_item_deleted = (await repository.list())[0]
    assert len(after_item_deleted["items"]) == 2
    await repository.delete(workflow_id)
    assert len(await repository.list()) == 0
    await database.close()
