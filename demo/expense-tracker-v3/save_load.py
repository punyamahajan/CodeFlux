import json
from pathlib import Path

def load_expenses(file_path=Path("expenses.json")):
    file_path = Path(file_path)
    if not file_path.is_file():
        return []

    contents = file_path.read_text(encoding="utf-8")
    if not contents.strip():
        return []
    return json.loads(contents)

def save_expenses(expenses, file_path=Path("expenses.json")):
    with open(file_path, 'w') as f:
        json.dump(expenses, f, indent=4)
