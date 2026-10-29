"""Work through a CodeFlux checklist using only the CodeFlux HTTP API.

For every unchecked task the runner fetches the task's handoff (its assigned model
plus the master prompt, the whole plan, and every earlier task's output), adds a
snapshot of the workspace folder, asks the model for the files to write, writes
them inside the workspace, and reports the result so the checklist ticks off.

    python -m codeflux.runner --workflow 3 --workspace demo/my-project
"""
from __future__ import annotations

import argparse
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from codeflux.checks import check_workspace

MAX_SNAPSHOT_CHARS = 60_000
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}

OUTPUT_FORMAT = """HOW TO REPLY. You are working through a shared checklist; other models handle the
other tasks. You cannot run commands, and describing a file does not create it. The ONLY way
to create or change a file is to reply with one block per file, exactly like this:

### FILE: relative/path/to/file.ext
```
full file content
```

Always give the complete file content, never a diff or "unchanged" placeholder.
Only write files needed for YOUR ASSIGNED TASK. Paths are relative to the workspace root.
Wire your code in: every feature must be reachable from the app's main entry point, not left
in a file nothing imports. Tests must never read, write, or delete the app's real data files;
use the tempfile module and pass the path in.
Finish with:

### SUMMARY
A few sentences on what you did, which files you wrote, and anything the next task must know."""

# A line holding only a file path ("### FILE: a.py", "### a.py", "**a.py**" or "a.py:")
# followed by a fenced code block. Small models rarely copy the exact marker.
FILE_BLOCK = re.compile(
    r"^(?:#{1,6}\s*|\*\*)?(?:FILE:\s*)?`?(?P<path>[\w./\\-]+\.\w{1,10})`?(?:\*\*)?:?[ \t]*\n+"
    r"```[^\n]*\n(?P<content>.*?)^```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
SUMMARY = re.compile(
    r"^(?:#{1,6}\s*|\*\*)?SUMMARY(?:\*\*)?:?[ \t]*\n(?P<summary>.*)", re.MULTILINE | re.DOTALL
)
RETRY = (
    "You did not write any files. Reply again with the complete content of every file your "
    "task needs, each as a '### FILE: path' line followed by a ``` code block, then ### SUMMARY."
)
MAX_FIX_ATTEMPTS = 2
MAX_REPAIR_ROUNDS = 4
ACCEPTANCE_FILE = "test_acceptance.py"

# Mistakes small models make in nearly every Streamlit app; added to prompts for Streamlit work.
STREAMLIT_RULES = """STREAMLIT RULES (the script reruns top to bottom on every click):
- st.button(...) is True only during the single rerun right after its click. Never put a form or
  input widgets inside `if st.button(...)`: the next click reruns without them and the input is lost.
  Show the form all the time (or toggle it with st.session_state / st.toggle).
- Load saved data once into st.session_state, change the session list, then save it. Never append
  file contents to a list on every rerun: totals will double.
- Handle a form inside `with st.form("name"):` and act on `if st.form_submit_button(...):`.
- Show results with st.write / st.metric / st.dataframe so they are visible right after submitting."""

ACCEPTANCE = """Write {file}: an automated acceptance test that uses the app EXACTLY like a person
would and checks every feature in the MASTER REQUEST. Do not import the app's internal functions;
drive the real entry point. Do not change any other file. Each test runs in an empty temporary
folder so the app's data files never touch the real ones.

For a Streamlit app, follow this template (streamlit.testing.v1.AppTest API):
```python
import os
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent / "main.py")  # the file the README says to run


def page_text(app):
    parts = [str(element.value) for kind in ("markdown", "text", "caption", "success", "info", "warning", "error") for element in getattr(app, kind)]
    parts += [f"{{metric.label}} {{metric.value}}" for metric in app.metric]
    parts += [frame.value.to_string() for frame in app.dataframe] + [table.value.to_string() for table in app.table]
    return "\\n".join(parts)


class AcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.previous = os.getcwd()
        self.folder = tempfile.TemporaryDirectory()
        os.chdir(self.folder.name)

    def tearDown(self):
        os.chdir(self.previous)
        self.folder.cleanup()

    def test_user_adds_an_item_and_sees_it(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        app.number_input[0].set_value(12.5)       # or app.text_input[0].input("..."), app.selectbox[0].select("...")
        app.text_input[0].input("Food")
        next(b for b in app.button if b.label == "Add").click().run()   # form submit buttons are in app.button too
        self.assertFalse(app.exception, [e.message for e in app.exception])
        self.assertIn("Food", page_text(app))

    def test_data_is_still_there_after_a_restart(self):
        ...  # add an item, then start a NEW AppTest.from_file(APP).run() and check it is shown
```
Widgets inside st.sidebar are in app.sidebar.button / app.sidebar.text_input etc.

For a command-line app, run it with subprocess.run([sys.executable, APP, ...], capture_output=True,
text=True, cwd=self.folder.name) and assert on stdout and the exit code.

CURRENT WORKSPACE FILES:
{snapshot}"""
REPAIR = """Every checklist task is done, but the finished project does not work yet. You are now
responsible for the whole project: make it work end to end without dropping features from the
master request. Later tasks may have broken files that earlier tasks wrote; make all files agree
with each other (names, imports, function signatures, data format) and make the tests match.
test_acceptance.py describes what the user must be able to do: when it fails, fix the APP so it
passes. test_acceptance.py is locked: changes to it are discarded.

PROBLEMS FOUND:
{problems}

FILES TO FIX FIRST: {files}

CURRENT WORKSPACE FILES:
{snapshot}"""
REVIEW = """You are reviewing a finished project against its MASTER REQUEST (given above).
The code compiles, its tests pass, and it loads. Decide whether a user running the main entry
point can actually do everything the MASTER REQUEST asks for. Also flag tests that touch the
app's real data files, and README instructions that refer to files or commands that do not exist.

Reply with exactly the word NONE if nothing is missing. Otherwise reply with one line per
problem, each starting with "- ", saying what is missing or wrong and in which file.

CURRENT WORKSPACE FILES:
{snapshot}"""
FIX = """CodeFlux checked the workspace after your reply and found problems:

{problems}

Fix them. Reply with the complete corrected content of every file you change, using the same
'### FILE: path' blocks, then ### SUMMARY. Do not remove features to make checks pass.

CURRENT WORKSPACE FILES:
{snapshot}"""


@dataclass
class StepResult:
    task_id: int
    task: str
    model: str
    provider: str
    files: list[str] = field(default_factory=list)
    summary: str = ""
    workflow_status: str = ""
    problems: list[str] = field(default_factory=list)  # left over after the fix attempts
    fix_attempts: int = 0


def severity(problems: list[str]) -> tuple[int, int]:
    """How broken a project is: (failing checks, review findings); lower is better.

    Counts individual failures inside a problem (each failing test, each undefined name) so a
    round that fixes three tests but breaks one still counts as progress.
    """
    checks = [problem for problem in problems if not problem.startswith("Review:")]
    failures = sum(
        max(1, len(re.findall(r"^(?:FAIL|ERROR):|F82\d", problem, re.MULTILINE))) for problem in checks
    )
    return failures, len(problems) - len(checks)


def parse_reply(text: str) -> tuple[dict[str, str], str]:
    files = {match["path"].strip(): match["content"] for match in FILE_BLOCK.finditer(text)}
    summary_match = SUMMARY.search(text)
    if summary_match:
        summary = summary_match["summary"].strip()
    else:
        summary = FILE_BLOCK.sub("", text).strip()
    return files, summary or "Task completed."


def safe_path(workspace: Path, relative: str) -> Path:
    target = (workspace / relative.strip().lstrip("/\\")).resolve()
    if not target.is_relative_to(workspace.resolve()):
        raise ValueError(f"refusing to write outside the workspace: {relative}")
    return target


def snapshot(workspace: Path) -> str:
    """List every workspace file with its content so the model sees the current state."""
    paths = sorted(
        path for path in workspace.rglob("*")
        if path.is_file() and not SKIP_DIRS.intersection(path.relative_to(workspace).parts)
    )
    if not paths:
        return "The workspace is empty."
    parts, budget = [], MAX_SNAPSHOT_CHARS
    for path in paths:
        relative = path.relative_to(workspace).as_posix()
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            parts.append(f"### {relative}\n(binary or unreadable file)")
            continue
        if len(content) > budget:
            parts.append(f"### {relative}\n(content omitted: snapshot size limit reached)")
            continue
        budget -= len(content)
        parts.append(f"### {relative}\n```\n{content}\n```")
    return "\n\n".join(parts)


class WorkflowRunner:
    def __init__(
        self, base_url: str, api_key: str, workspace: Path, client: httpx.Client | None = None,
        verify: bool = True,
    ):
        # Accept the SDK-style ".../v1" base URL as well as the bare gateway address.
        self.base_url = base_url.rstrip("/").removesuffix("/v1")
        self.workspace = workspace
        self.verify = verify
        # Local models can take minutes to write several files.
        self.client = client or httpx.Client(timeout=600)
        self.context: list[dict] = []  # master prompt and plan, kept for the final repair
        self.last_model: str | None = None
        self.final_problems: list[str] | None = None  # set once a run finishes the checklist
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def _request(self, method: str, path: str, **kwargs) -> dict:
        response = self.client.request(method, f"{self.base_url}{path}", headers=self.headers, **kwargs)
        if response.is_error:
            try:
                message = response.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                message = response.text[:300]
            raise RuntimeError(f"{method} {path} returned {response.status_code}: {message}")
        return response.json()

    def _chat(self, model: str, messages: list[dict]) -> dict:
        return self._request("POST", "/v1/chat/completions", json={"model": model, "messages": messages})

    def run_next(
        self, workflow_id: int, on_start: Callable[[str, str], None] | None = None
    ) -> StepResult | None:
        """Do one task. Returns None when every task is already checked."""
        task = self._request("GET", f"/v1/ide/workflows/{workflow_id}/next-task")["task"]
        if task is None:
            return None
        if on_start:
            on_start(task["task"], task["model"])
        self.context, self.last_model = task["messages"], task["model"]
        self.workspace.mkdir(parents=True, exist_ok=True)
        messages = [
            *task["messages"],
            # Format rules go last: small models follow the end of the prompt most reliably.
            {"role": "user", "content": f"CURRENT WORKSPACE FILES:\n{snapshot(self.workspace)}\n\n{self._rules()}{OUTPUT_FORMAT}"},
        ]
        body = self._chat(task["model"], messages)
        reply = body["choices"][0]["message"]["content"] or ""
        files, summary = parse_reply(reply)
        if not files:
            messages += [{"role": "assistant", "content": reply}, {"role": "user", "content": RETRY}]
            body = self._chat(task["model"], messages)
            reply = body["choices"][0]["message"]["content"] or ""
            files, retry_summary = parse_reply(reply)
            summary = retry_summary if files else summary
        self._write(files)

        # Check the work and hand any failure back to the same model to fix.
        problems = check_workspace(self.workspace) if self.verify and files else []
        attempts = 0
        while problems and attempts < MAX_FIX_ATTEMPTS:
            attempts += 1
            messages += [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": self._rules() + FIX.format(problems="\n\n".join(problems), snapshot=snapshot(self.workspace))},
            ]
            body = self._chat(task["model"], messages)
            reply = body["choices"][0]["message"]["content"] or ""
            fixed, fix_summary = parse_reply(reply)
            if fixed:
                self._write(fixed)
                files.update(fixed)
                summary += f"\n\nFix {attempts}: {fix_summary}"
            problems = check_workspace(self.workspace)

        provider = body.get("codeflux", {}).get("provider", "unknown")
        if not files:
            checks = "**No files were written**: the model did not return any file blocks."
        elif not self.verify:
            checks = "Checks: skipped."
        elif problems:
            checks = "**Checks failed** — the next task should fix:\n\n" + "\n\n".join(
                f"```\n{problem}\n```" for problem in problems
            )
        else:
            checks = "Checks: passed (compiles, tests, app loads)" + (
                f" after {attempts} fix attempt(s)." if attempts else "."
            )
        report = (
            f"_Model: `{task['model']}` via `{provider}`_\n\n{summary}\n\n"
            + (f"Files written: {', '.join(f'`{name}`' for name in files)}\n\n" if files else "")
            + checks
        )
        completed = self._request(
            "POST", task["completion_url"], json={"result": report}
        )
        return StepResult(
            task_id=task["task_id"], task=task["task"], model=task["model"], provider=provider,
            files=list(files), summary=summary, workflow_status=completed["workflow_status"],
            problems=problems, fix_attempts=attempts,
        )

    def _write(self, files: dict[str, str]) -> None:
        for relative, content in files.items():
            target = safe_path(self.workspace, relative)
            if target.parent.is_dir() and not target.exists():
                # "VIEW.PY" for view.py: reuse the existing name rather than renaming the file
                # (Windows) or creating a near-duplicate (elsewhere).
                target = next(
                    (path for path in target.parent.iterdir() if path.name.lower() == target.name.lower()),
                    target,
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def repair(
        self, model: str, on_round: Callable[[int, list[str], list[str]], None] | None = None,
    ) -> list[str]:
        """Check the finished project and keep asking for whole-project fixes until it passes.

        Per-task fixes only see one task; later tasks often break files earlier ones wrote, so
        this pass looks at everything together. Returns the problems still left (empty = works).
        """
        problems = check_workspace(self.workspace) or self.review(model)
        for round_number in range(1, MAX_REPAIR_ROUNDS + 1):
            if not problems:
                break
            text = "\n\n".join(problems)
            named = sorted({name for name in re.findall(r"[\w./-]+\.(?:py|md|json|txt)", text)
                            if (self.workspace / name).exists()})
            prompt = REPAIR.format(
                problems=text, files=", ".join(named) or "see the problems above",
                snapshot=snapshot(self.workspace),
            )
            body = self._chat(model, [*self._project_context(), {"role": "user", "content": f"{prompt}\n\n{self._rules()}{OUTPUT_FORMAT}"}])
            files, _ = parse_reply(body["choices"][0]["message"]["content"] or "")
            # The acceptance test is the spec: left editable, small models weaken it until it
            # passes instead of fixing the app.
            files = {name: text for name, text in files.items() if Path(name).name.lower() != ACCEPTANCE_FILE}
            before = self._backup()
            self._write(files)
            result = check_workspace(self.workspace) or self.review(model)
            if severity(result) > severity(problems):
                # A small model's "fix" often breaks more than it mends; keep the better state.
                self._restore(before)
                result = problems
                files = {}
            problems = result
            if on_round:
                on_round(round_number, list(files), problems)
        return problems

    def _backup(self) -> dict[Path, str]:
        return {
            path: path.read_text(encoding="utf-8")
            for path in self.workspace.rglob("*")
            if path.is_file() and path.suffix in {".py", ".md", ".txt", ".toml"}
            and not SKIP_DIRS.intersection(path.relative_to(self.workspace).parts)
        }

    def _restore(self, backup: dict[Path, str]) -> None:
        for path in set(self._backup()) - set(backup):
            path.unlink()  # files the rejected round created
        for path, content in backup.items():
            path.write_text(content, encoding="utf-8")

    def _rules(self) -> str:
        """Extra rules for the frameworks this project uses, put in front of the format rules."""
        text = " ".join(str(message.get("content")) for message in self.context).lower()
        uses_streamlit = "streamlit" in text or any(
            "import streamlit" in path.read_text(encoding="utf-8", errors="ignore")
            for path in self.workspace.glob("*.py")
        )
        return f"{STREAMLIT_RULES}\n\n" if uses_streamlit else ""

    def write_acceptance_test(self, model: str) -> list[str]:
        """Have the model write a test that uses the finished app like a person would.

        Compiling, unit tests, and a load check all pass for an app whose form can never be
        submitted. Driving the real UI through each requested feature catches that; the repair
        rounds then fix the app until this test passes. Returns the files written.
        """
        if (self.workspace / ACCEPTANCE_FILE).exists():
            return []
        prompt = ACCEPTANCE.format(file=ACCEPTANCE_FILE, snapshot=snapshot(self.workspace))
        body = self._chat(model, [*self._project_context(), {"role": "user", "content": f"{prompt}\n\n{OUTPUT_FORMAT}"}])
        files, _ = parse_reply(body["choices"][0]["message"]["content"] or "")
        # Only the acceptance test is written here; the repair rounds fix the app itself.
        content = next((text for name, text in files.items() if Path(name).name == ACCEPTANCE_FILE), None)
        if content is None:
            return []
        self._write({ACCEPTANCE_FILE: content})
        return [ACCEPTANCE_FILE]

    def _project_context(self) -> list[dict]:
        """The last task's handoff minus its "YOUR ASSIGNED TASK" part.

        Left in, the model keeps redoing that one task (the README, say) instead of fixing
        the files the checks point at.
        """
        trimmed = []
        for message in self.context:
            content = message.get("content")
            if isinstance(content, str) and "YOUR ASSIGNED TASK:" in content:
                content = content.split("YOUR ASSIGNED TASK:")[0].rstrip()
            trimmed.append({**message, "content": content})
        return trimmed

    def review(self, model: str) -> list[str]:
        """Ask the model whether the working code does what the master request asked for.

        Automated checks prove the code runs, not that it is complete: a feature left in a file
        nothing calls passes every check. Returns the missing items (empty = complete).
        """
        prompt = REVIEW.format(snapshot=snapshot(self.workspace))
        body = self._chat(model, [*self._project_context(), {"role": "user", "content": prompt}])
        reply = (body["choices"][0]["message"]["content"] or "").strip()
        if not reply or re.match(r"^\W*none\b", reply, re.IGNORECASE):
            return []
        items = [line.strip()[2:].strip() for line in reply.splitlines() if line.strip().startswith(("- ", "* "))]
        return [f"Review: {item}" for item in items or [reply[:1000]]]

    def run(
        self, workflow_id: int, max_tasks: int | None = None,
        on_start: Callable[[str, str], None] | None = None,
        on_done: Callable[[StepResult], None] | None = None,
        on_repair: Callable[[int, list[str], list[str]], None] | None = None,
        on_acceptance: Callable[[list[str]], None] | None = None,
    ) -> list[StepResult]:
        results: list[StepResult] = []
        while max_tasks is None or len(results) < max_tasks:
            step = self.run_next(workflow_id, on_start)
            if step is None:
                break
            results.append(step)
            if on_done:
                on_done(step)
        finished = results and results[-1].workflow_status == "completed"
        if finished and self.verify and self.last_model:
            written = self.write_acceptance_test(self.last_model)
            if on_acceptance:
                on_acceptance(written)
            self.final_problems = self.repair(self.last_model, on_repair)
        return results


def main() -> None:
    from codeflux.config import Settings

    settings = Settings()
    parser = argparse.ArgumentParser(description="Run a CodeFlux checklist through the CodeFlux API.")
    parser.add_argument("--workflow", type=int, required=True, help="workflow id shown in the dashboard")
    parser.add_argument("--workspace", type=Path, default=Path("demo"), help="folder the models work in")
    parser.add_argument("--base-url", default=os.getenv("CODEFLUX_BASE_URL", settings.dashboard_gateway_url))
    parser.add_argument("--api-key", default=os.getenv("CODEFLUX_API_KEY") or settings.admin_key())
    parser.add_argument("--max-tasks", type=int, default=None)
    parser.add_argument(
        "--no-checks", action="store_true",
        help="skip compiling, testing, and smoke-running the generated code",
    )
    args = parser.parse_args()
    if not args.api_key:
        parser.error("pass --api-key or set CODEFLUX_API_KEY")

    def started(task: str, model: str) -> None:
        print(f"[working] {task}  (model: {model})", flush=True)

    def done(step: StepResult) -> None:
        print(f"[done]    {step.task}  (answered by {step.provider})")
        for name in step.files:
            print(f"          wrote {name}")
        fixes = f" after {step.fix_attempts} fix(es)" if step.fix_attempts else ""
        if step.problems:
            print(f"          CHECKS FAILED{fixes}: {step.problems[0].splitlines()[0]}")
        elif step.files and not args.no_checks:
            print(f"          checks passed{fixes}")

    def repaired(round_number: int, files: list[str], problems: list[str]) -> None:
        state = f"still failing: {problems[0].splitlines()[0]}" if problems else "project works"
        print(f"[repair {round_number}] wrote {', '.join(files) or 'nothing'}; {state}", flush=True)

    runner = WorkflowRunner(args.base_url, args.api_key, args.workspace, verify=not args.no_checks)
    def accepted(files: list[str]) -> None:
        print(f"[acceptance] {'wrote ' + ACCEPTANCE_FILE if files else 'no new acceptance test'}", flush=True)

    results = runner.run(
        args.workflow, args.max_tasks, on_start=started, on_done=done, on_repair=repaired, on_acceptance=accepted,
    )
    print(f"Finished {len(results)} task(s). Files are in {args.workspace.resolve()}")
    if runner.final_problems is not None:
        failing = runner.final_problems
        print("Final check: " + ("FAILED\n" + "\n".join(failing) if failing else "passed (checks and review)"))


if __name__ == "__main__":
    main()
