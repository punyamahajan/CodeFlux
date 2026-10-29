import unittest
import os
import tempfile
import json
import data_manager

class TestDataManager(unittest.TestCase):
    def setUp(self):
        # Create a temporary file for testing
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_file = os.path.join(self.test_dir.name, "test_expenses.json")
        # Monkeypatch the FILE_PATH in data_manager
        data_manager.FILE_PATH = self.test_file

    def tearDown(self):
        self.test_dir.cleanup()

    def test_save_and_load(self):
        expenses = [{"amount": 10.0, "category": "Food"}]
        data_manager.save_expenses(expenses)
        loaded = data_manager.load_expenses()
        self.assertEqual(loaded, expenses)

    def test_calculate_totals(self):
        expenses = [
            {"amount": 10.0, "category": "Food"},
            {"amount": 5.0, "category": "Food"},
            {"amount": 20.0, "category": "Transport"}
        ]
        totals = data_manager.calculate_category_totals(expenses)
        self.assertEqual(totals["Food"], 15.0)
        self.assertEqual(totals["Transport"], 20.0)

    def test_load_empty(self):
        self.assertEqual(data_manager.load_expenses(), [])

if __name__ == "__main__":
    unittest.main()
