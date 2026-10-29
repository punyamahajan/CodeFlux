import json

import httpx

from codeflux.checks import check_workspace
from codeflux.runner import WorkflowRunner

GOOD_MODULE = "def add(a, b):\n    return a + b\n"
GOOD_TEST = (
    "import unittest\nfrom calc import add\n\n"
    "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 2), 4)\n"
)


def write(folder, files):
    for name, content in files.items():
        (folder / name).write_text(content, encoding="utf-8")


def test_working_project_passes(tmp_path):
    write(tmp_path, {"calc.py": GOOD_MODULE, "test_calc.py": GOOD_TEST})
    assert check_workspace(tmp_path) == []


def test_syntax_error_is_reported(tmp_path):
    write(tmp_path, {"calc.py": "def add(a, b)\n    return a + b\n"})
    [problem] = check_workspace(tmp_path)
    assert "calc.py does not compile" in problem


def test_failing_tests_are_reported_with_output(tmp_path):
    write(tmp_path, {"calc.py": "def add(a, b):\n    return a - b\n", "test_calc.py": GOOD_TEST})
    [problem] = check_workspace(tmp_path)
    assert "tests fail" in problem and "AssertionError" in problem


def test_streamlit_app_crash_is_reported(tmp_path):
    write(tmp_path, {
        "store.py": "class Store:\n    def items(self):\n        return self.missing\n",
        "app.py": "import streamlit as st\nfrom store import Store\nst.title('x')\nst.write(Store().items())\n",
    })
    [problem] = check_workspace(tmp_path)
    assert "app.py crashes" in problem and "missing" in problem


def test_working_streamlit_app_passes(tmp_path):
    write(tmp_path, {"app.py": "import streamlit as st\nst.title('Hello')\nst.button('Go')\n"})
    assert check_workspace(tmp_path) == []


def test_runner_sends_failures_back_until_fixed(tmp_path):
    replies = iter([
        (
            "### FILE: calc.py\n```\ndef add(a, b):\n    return a - b\n```\n"
            f"### FILE: test_calc.py\n```\n{GOOD_TEST}```\n### SUMMARY\nWrote it."
        ),
        "### FILE: calc.py\n```\ndef add(a, b):\n    return a + b\n```\n### SUMMARY\nFixed the sign.",
        "No acceptance test today.",  # acceptance step: model writes nothing usable
        "NONE",  # final review: nothing missing
    ])
    chats: list[list[dict]] = []
    reports: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/next-task"):
            if reports:
                return httpx.Response(200, json={"task": None})
            return httpx.Response(200, json={"task": {
                "task_id": 1, "task": "Write calc", "model": "m",
                "completion_url": "/v1/ide/workflows/1/tasks/1/complete", "messages": [],
            }})
        if request.url.path == "/v1/chat/completions":
            chats.append(json.loads(request.content)["messages"])
            return httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}}]})
        reports.append(json.loads(request.content)["result"])
        return httpx.Response(200, json={"workflow_status": "completed"})

    runner = WorkflowRunner("http://gateway", "k", tmp_path, httpx.Client(transport=httpx.MockTransport(handler)))
    [step] = runner.run(1)
    assert "The tests fail" in chats[1][-1]["content"]  # the failure went back to the model
    assert step.fix_attempts == 1 and step.problems == []
    assert "Checks: passed" in reports[0] and "after 1 fix attempt" in reports[0]
    assert check_workspace(tmp_path) == []


def test_final_repair_fixes_what_task_fixes_could_not(tmp_path):
    broken = "### FILE: calc.py\n```\ndef add(a, b):\n    return a - b\n```\n### SUMMARY\nTried."
    replies = iter([
        (
            "### FILE: calc.py\n```\ndef add(a, b):\n    return a - b\n```\n"
            f"### FILE: test_calc.py\n```\n{GOOD_TEST}```\n### SUMMARY\nWrote it."
        ),
        broken,
        broken,
        "No acceptance test.",
        "### FILE: calc.py\n```\ndef add(a, b):\n    return b + a\n```\n### SUMMARY\nRepaired.",
        "NONE",  # review after the repair
    ])
    chats: list[list[dict]] = []
    reported: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/next-task"):
            if reported:
                return httpx.Response(200, json={"task": None})
            return httpx.Response(200, json={"task": {
                "task_id": 1, "task": "Write calc", "model": "m",
                "completion_url": "/v1/ide/workflows/1/tasks/1/complete",
                "messages": [{"role": "user", "content": "MASTER REQUEST: calculator"}],
            }})
        if request.url.path == "/v1/chat/completions":
            chats.append(json.loads(request.content)["messages"])
            return httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}}]})
        reported.append(json.loads(request.content)["result"])
        return httpx.Response(200, json={"workflow_status": "completed"})

    rounds: list[tuple[int, list[str]]] = []
    runner = WorkflowRunner("http://gateway", "k", tmp_path, httpx.Client(transport=httpx.MockTransport(handler)))
    [step] = runner.run(1, on_repair=lambda number, files, problems: rounds.append((number, problems)))
    assert step.problems and "**Checks failed**" in reported[0]
    assert rounds == [(1, [])]
    assert "does not work yet" in chats[-2][-1]["content"]
    assert chats[-2][0]["content"] == "MASTER REQUEST: calculator"  # repair keeps the full context
    assert "reviewing a finished project" in chats[-1][-1]["content"]
    assert runner.final_problems == []
    assert check_workspace(tmp_path) == []


def test_undefined_name_is_reported_even_when_nothing_runs_it(tmp_path):
    write(tmp_path, {"totals.py": "def show():\n    return format_total(3)\n"})
    [problem] = check_workspace(tmp_path)
    assert "Undefined names" in problem and "`format_total`" in problem


def test_review_lists_missing_features_and_none_means_complete(tmp_path):
    replies = iter(["- totals per category are never shown in app.py\n- README mentions requirements.txt", "NONE."])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}}]})

    runner = WorkflowRunner("http://gateway", "k", tmp_path, httpx.Client(transport=httpx.MockTransport(handler)))
    assert runner.review("m") == [
        "Review: totals per category are never shown in app.py",
        "Review: README mentions requirements.txt",
    ]
    assert runner.review("m") == []


def test_repair_context_drops_the_last_assigned_task(tmp_path):
    write(tmp_path, {"calc.py": "def add(a, b):\n    return as_text(a + b)\n"})
    sent: list[list[dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content)["messages"])
        return httpx.Response(200, json={"choices": [{"message": {"content": (
            "### FILE: calc.py\n```\ndef as_text(value):\n    return str(value)\n\n\n"
            "def add(a, b):\n    return as_text(a + b)\n```\n"
        )}}]})

    runner = WorkflowRunner("http://gateway", "k", tmp_path, httpx.Client(transport=httpx.MockTransport(handler)))
    runner.context = [{"role": "user", "content": "MASTER REQUEST:\nCalc\n\nYOUR ASSIGNED TASK:\nWrite README.md"}]
    runner.review = lambda model: []
    assert runner.repair("m") == []
    assert sent[0][0]["content"] == "MASTER REQUEST:\nCalc"
    assert "FILES TO FIX FIRST: calc.py" in sent[0][-1]["content"]


def test_missing_standard_imports_are_added_automatically(tmp_path):
    write(tmp_path, {
        "store.py": '"""Store."""\nfrom __future__ import annotations\n\ndef save(p):\n    return json.dumps(os.sep)\n',
        "app.py": "def show():\n    st.write(undefined_thing)\n",
    })
    from codeflux.checks import add_missing_imports
    assert sorted(add_missing_imports(tmp_path)) == [
        "app.py: import streamlit as st", "store.py: import json", "store.py: import os",
    ]
    assert (tmp_path / "store.py").read_text().startswith(
        '"""Store."""\nfrom __future__ import annotations\nimport json\nimport os\n'
    )
    [problem] = check_workspace(tmp_path)  # a genuinely unknown name still goes to the model
    assert "undefined_thing" in problem and "`st`" not in problem


def test_tests_named_x_test_py_are_run_too(tmp_path):
    write(tmp_path, {"calc.py": "def add(a, b):\n    return a - b\n", "calc_test.py": GOOD_TEST})
    [problem] = check_workspace(tmp_path)
    assert "tests fail" in problem


ACCEPTANCE_REPLY = (
    "### FILE: test_acceptance.py\n```\n"
    "import subprocess, sys, unittest\nfrom pathlib import Path\n\n"
    "APP = str(Path(__file__).resolve().parent / 'cli.py')\n\n"
    "class A(unittest.TestCase):\n"
    "    def test_adds(self):\n"
    "        out = subprocess.run([sys.executable, APP, '2', '3'], capture_output=True, text=True).stdout\n"
    "        self.assertEqual(out.strip(), '5')\n```\n"
    "### FILE: cli.py\n```\nprint('sneaky change')\n```\n"
)


def test_acceptance_test_drives_the_app_and_its_failure_is_repaired(tmp_path):
    write(tmp_path, {"cli.py": "import sys\nprint(int(sys.argv[1]) - int(sys.argv[2]))\n"})
    replies = iter([
        ACCEPTANCE_REPLY,
        "### FILE: cli.py\n```\nimport sys\nprint(int(sys.argv[1]) + int(sys.argv[2]))\n```\n",
        "NONE",
    ])
    prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        prompts.append(json.loads(request.content)["messages"][-1]["content"])
        return httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}}]})

    runner = WorkflowRunner("http://gateway", "k", tmp_path, httpx.Client(transport=httpx.MockTransport(handler)))
    runner.context = [{"role": "user", "content": "MASTER REQUEST:\nA CLI that adds two numbers"}]
    assert runner.write_acceptance_test("m") == ["test_acceptance.py"]
    assert "print(int(sys.argv[1]) - int(sys.argv[2]))" in (tmp_path / "cli.py").read_text()  # app untouched
    assert runner.write_acceptance_test("m") == []  # an existing acceptance test is kept
    assert runner.repair("m") == []
    assert "tests fail" in prompts[1] and "fix the APP" in prompts[1]
    assert check_workspace(tmp_path) == []


def test_streamlit_rules_are_added_only_for_streamlit_projects(tmp_path):
    runner = WorkflowRunner("http://gateway", "k", tmp_path, httpx.Client())
    runner.context = [{"role": "user", "content": "MASTER REQUEST:\nA CLI calculator"}]
    assert runner._rules() == ""
    runner.context = [{"role": "user", "content": "MASTER REQUEST:\nA Streamlit expense tracker"}]
    assert "Never put a form or" in runner._rules()


def test_checks_do_not_leave_data_files_behind(tmp_path):
    write(tmp_path, {
        "store.py": "import json\n\ndef save(items, path='data.json'):\n    open(path, 'w').write(json.dumps(items))\n",
        "test_store.py": "import unittest\nfrom store import save\n\nclass T(unittest.TestCase):\n    def test_save(self):\n        save([1])\n",
    })
    assert check_workspace(tmp_path) == []
    assert not (tmp_path / "data.json").exists()


def test_a_repair_that_makes_things_worse_is_rolled_back(tmp_path):
    write(tmp_path, {"calc.py": "def add(a, b):\n    return a - b\n", "test_calc.py": GOOD_TEST})
    worse = (
        "### FILE: calc.py\n```\ndef add(a, b):\n    return a - b\n\ndef sub(a, b):\n    return minus(a, b)\n```\n"
        "### FILE: extra.py\n```\nvalue = undefined_one + undefined_two\n```\n"
    )
    replies = iter([worse, "### FILE: calc.py\n```\ndef add(a, b):\n    return a + b\n```\n", "NONE"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}}]})

    runner = WorkflowRunner("http://gateway", "k", tmp_path, httpx.Client(transport=httpx.MockTransport(handler)))
    rounds: list[list[str]] = []
    assert runner.repair("m", lambda number, files, problems: rounds.append(files)) == []
    assert rounds == [[], ["calc.py"]]  # round 1 was rejected and undone
    assert not (tmp_path / "extra.py").exists()


def test_repair_cannot_edit_the_acceptance_test_and_keeps_file_name_case(tmp_path):
    write(tmp_path, {"view.py": "def show():\n    return missing_name\n", "test_acceptance.py": "# spec\n"})
    reply = (
        "### FILE: test_acceptance.py\n```\n# weakened\n```\n"
        "### FILE: VIEW.PY\n```\ndef show():\n    return 1\n```\n"
    )
    replies = iter([reply, "NONE"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}}]})

    runner = WorkflowRunner("http://gateway", "k", tmp_path, httpx.Client(transport=httpx.MockTransport(handler)))
    assert runner.repair("m") == []
    assert (tmp_path / "test_acceptance.py").read_text() == "# spec\n"
    assert sorted(path.name for path in tmp_path.glob("*.py")) == ["test_acceptance.py", "view.py"]
    assert "return 1" in (tmp_path / "view.py").read_text()
