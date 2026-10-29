import json
from models import Expense

def load_expenses():
    try:
        with open("expenses.json", "r") as file:
            return [Expense(**expense) for expense in json.load(file)]
    except FileNotFoundError:
        return []

def save_expenses(expenses):
    try:
        with open("expenses.json", "w") as file:
            json.dump([vars(expense) for expense in expenses], file, indent=4)
    except IOError:
        print("Error saving expenses")
