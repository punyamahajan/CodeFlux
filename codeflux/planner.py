"""Turn a master prompt into a checklist that file-writing models can complete."""
from __future__ import annotations

import json
import re

# Each task is later done by a model that can only write files, so the plan must only contain
# coding work; steps like "install Python" or "deploy" made models invent junk files.
PLANNER_PROMPT = (
    "Turn the user's project request into a checklist for AI coding agents that can ONLY create "
    "and edit files in an empty project folder. Return only a JSON array of 3 to 8 concise task "
    "strings, ordered by dependency. Every task must produce or change specific files and should "
    "name them. Never include tasks to install software, create accounts, deploy, run manual tests, "
    "or anything that cannot be done by writing files. Prefer Python and the standard library "
    "unless the request says otherwise. The last task must add unittest tests (test_*.py) for the "
    "core logic and a short README.md. Do not execute the work."
)


MAX_TASKS = 8
# Steps a file-writing model cannot do; small models add them despite the prompt.
NOT_CODING = re.compile(
    r"^\s*(?:install|deploy|run|launch|start|open|test (?:and debug )?(?:the|your) (?:app|website)|"
    r"create (?:a )?(?:new )?(?:project )?folder|set ?up (?:a )?(?:virtual|venv|environment))\b",
    re.IGNORECASE,
)


def _task_text(item: object) -> str:
    # Small models often return objects such as {"Task": "...", "Files": [...]}.
    if isinstance(item, dict):
        for key in ("task", "Task", "title", "name", "description"):
            if isinstance(item.get(key), str):
                return item[key].strip()
        return ""
    return str(item).strip()


def checklist_from_response(text: str) -> list[str]:
    items: list[str] = []
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            values = json.loads(match.group(0))
            if isinstance(values, list):
                items = [_task_text(item) for item in values]
        except json.JSONDecodeError:
            pass
    if not any(items):
        items = [
            re.sub(r"^\s*(?:[-*]|\d+[.)])?\s*(?:\[[ xX]\])?\s*", "", line).strip()
            for line in text.splitlines()
            if re.match(r"^\s*(?:[-*]|\d+[.)]|\[[ xX]\])\s+", line)
        ]
    seen: set[str] = set()
    tasks = []
    for item in items:
        if item and not NOT_CODING.match(item) and item.lower() not in seen:
            seen.add(item.lower())
            tasks.append(item)
    return tasks[:MAX_TASKS] or ["Review and refine the plan before execution"]
