import json
from pathlib import Path

def load_expenses(file_path=Path("expenses.json")):
    if file_path.is_file():
        with open(file_path, 'r') as f:
            return json.load(f)
    return []

def save_expenses(expenses, file_path=Path("expenses.json")):
    with open(file_path, 'w') as f:
        json.dump(expenses, f, indent=4)
