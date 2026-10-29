import json
import unittest
from save_load import load_expenses, save_expenses
import tempfile
from expenses import ExpenseManager

class TestSaveLoad(unittest.TestCase):
    def test_load_expenses(self):
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.json') as tmp:
            tmp.write('[]')
            tmp_filename = tmp.name
            expenses = load_expenses(tmp_filename)
            self.assertEqual(expenses, [])

    def test_save_expenses(self):
        expenses = [{"amount": 100, "category": "Groceries"}]
        tmp_filename = tempfile.NamedTemporaryFile('w', delete=False, suffix='.json').name
        save_expenses(expenses, tmp_filename)
        with open(tmp_filename, 'r') as f:
            saved_expenses = json.load(f)
            self.assertEqual(saved_expenses, expenses)

    def test_save_and_load_expenses(self):
        expense_manager = ExpenseManager()
        expense_manager.add_expense(100, "Groceries")
        expense_manager.add_expense(50, "Utilities")
        temp_filename = tempfile.NamedTemporaryFile('w', delete=False, suffix='.json').name
        save_expenses(expense_manager.get_expenses(), temp_filename)
        loaded_expenses = load_expenses(temp_filename)
        self.assertEqual(len(loaded_expenses), 2)
        self.assertEqual(loaded_expenses[0], {"amount": 100, "category": "Groceries"})
        self.assertEqual(loaded_expenses[1], {"amount": 50, "category": "Utilities"})

if __name__ == '__main__':
    unittest.main()
