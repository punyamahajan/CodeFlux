import json
import os

# Default file path
FILE_PATH = "expenses.json"

def load_expenses(filepath=None):
    """Loads expenses from the JSON file."""
    path = filepath or FILE_PATH
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def save_expenses(expenses, filepath=None):
    """Saves the list of expenses to the JSON file."""
    path = filepath or FILE_PATH
    with open(path, "w") as f:
        json.dump(expenses, f, indent=4)

def add_expense(amount, category, filepath=None):
    """Appends a new expense record and saves to file."""
    path = filepath or FILE_PATH
    expenses = load_expenses(path)
    expenses.append({
        "amount": float(amount),
        "category": category
    })
    save_expenses(expenses, path)

def calculate_category_totals(expenses):
    """Calculates the sum of expenses grouped by category."""
    category_totals = {}
    for expense in expenses:
        category = expense["category"]
        amount = expense["amount"]
        category_totals[category] = category_totals.get(category, 0) + amount
    return category_totals
