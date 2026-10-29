import json

import httpx
import pytest

from codeflux.runner import WorkflowRunner, parse_reply, safe_path

REPLY = """Here is the work.

### FILE: app/main.py
```python
print("hi")
```

### FILE: `README.md`
```markdown
# Demo
```

### SUMMARY
Wrote the entry point and README.
"""


def test_parse_reply_extracts_files_and_summary():
    files, summary = parse_reply(REPLY)
    assert files == {"app/main.py": 'print("hi")\n', "README.md": "# Demo\n"}
    assert summary == "Wrote the entry point and README."


@pytest.mark.parametrize("header", ["### cli.py", "**cli.py**", "cli.py:", "## FILE: `cli.py`"])
def test_parse_reply_accepts_common_header_styles(header):
    files, _ = parse_reply(f"Intro text.\n\n{header}\n```python\nimport sys\n```\n")
    assert files == {"cli.py": "import sys\n"}


def test_prose_mentioning_a_file_is_not_a_file_block():
    assert parse_reply("Run test.py to check.\n```\npython test.py\n```")[0] == {}


def test_parse_reply_without_markers_uses_text_as_summary():
    assert parse_reply("Just some advice.") == ({}, "Just some advice.")


def test_safe_path_blocks_escaping_the_workspace(tmp_path):
    assert safe_path(tmp_path, "a/b.txt") == (tmp_path / "a" / "b.txt").resolve()
    with pytest.raises(ValueError):
        safe_path(tmp_path, "../outside.txt")


def test_runner_does_every_task_with_its_model_and_shared_context(tmp_path):
    tasks = [
        {"task_id": 1, "task": "Write the code", "model": "gpt-4-tier"},
        {"task_id": 2, "task": "Write the docs", "model": "gemini-tier"},
    ]
    done: list[dict] = []
    chat_requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer cf_test"
        if request.url.path.endswith("/next-task"):
            remaining = tasks[len(done):]
            if not remaining:
                return httpx.Response(200, json={"task": None})
            task = remaining[0]
            earlier = "\n".join(item["result"] for item in done) or "No earlier task output."
            return httpx.Response(200, json={"task": {
                **task,
                "completion_url": f"/v1/ide/workflows/7/tasks/{task['task_id']}/complete",
                "messages": [{"role": "user", "content": f"YOUR TASK: {task['task']}\nEARLIER:\n{earlier}"}],
            }})
        if request.url.path == "/v1/chat/completions":
            payload = json.loads(request.content)
            chat_requests.append(payload)
            name = "main.py" if len(chat_requests) == 1 else "README.md"
            content = f"### FILE: {name}\n```\ncontent {len(chat_requests)}\n```\n### SUMMARY\nDid step {len(chat_requests)}."
            return httpx.Response(200, json={
                "choices": [{"message": {"content": content}}], "codeflux": {"provider": "fake"},
            })
        if request.url.path.endswith("/complete"):
            done.append(json.loads(request.content))
            status = "completed" if len(done) == len(tasks) else "in_progress"
            return httpx.Response(200, json={"workflow_status": status})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    runner = WorkflowRunner("http://gateway", "cf_test", tmp_path / "demo", client, verify=False)
    started: list[tuple[str, str]] = []
    steps = runner.run(7, on_start=lambda task, model: started.append((task, model)))

    assert [step.task for step in steps] == ["Write the code", "Write the docs"]
    assert [request["model"] for request in chat_requests] == ["gpt-4-tier", "gemini-tier"]
    assert started == [("Write the code", "gpt-4-tier"), ("Write the docs", "gemini-tier")]
    second_prompt = "\n".join(message["content"] for message in chat_requests[1]["messages"])
    assert "Did step 1." in second_prompt  # earlier task output is handed on
    assert "### main.py" in second_prompt and "content 1" in second_prompt  # current files too
    assert (tmp_path / "demo" / "main.py").read_text() == "content 1\n"
    assert (tmp_path / "demo" / "README.md").read_text() == "content 2\n"
    assert steps[-1].workflow_status == "completed"
    assert "`gpt-4-tier` via `fake`" in done[0]["result"]


def test_runner_asks_again_when_no_files_are_returned(tmp_path):
    replies = iter(["I created main.py for you.", "### FILE: main.py\n```\nok\n```\n### SUMMARY\nDone."])
    reported: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/next-task"):
            if reported:
                return httpx.Response(200, json={"task": None})
            return httpx.Response(200, json={"task": {
                "task_id": 1, "task": "Write main.py", "model": "m",
                "completion_url": "/v1/ide/workflows/1/tasks/1/complete", "messages": [],
            }})
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}}]})
        reported.append(json.loads(request.content)["result"])
        return httpx.Response(200, json={"workflow_status": "completed"})

    runner = WorkflowRunner("http://gateway/v1", "k", tmp_path, httpx.Client(transport=httpx.MockTransport(handler)), verify=False)
    [step] = runner.run(1)
    assert step.files == ["main.py"]
    assert (tmp_path / "main.py").read_text() == "ok\n"
    assert "Files written: `main.py`" in reported[0]
