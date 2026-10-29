import json
import os

def save_expenses(data):
    file_path = "expenses.json"
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            existing_data = json.load(file)
    else:
        existing_data = []

    existing_data.extend(data)

    with open(file_path, 'w') as file:
        json.dump(existing_data, file, indent=4)

def load_expenses():
    file_path = "expenses.json"
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            return json.load(file)
    else:
        return []

