import unittest
from expenses_manager import save_expenses, load_expenses

class TestExpensesManager(unittest.TestCase):
    def test_save_expenses(self):
        # Test the save_expenses function
        test_data = [
            {"amount": 100.00, "category": "Food"},
            {"amount": 50.00, "category": "Transportation"}
        ]
        
        # Save the test data
        save_expenses(test_data)
        
        # Load the expenses from the file
        expenses = load_expenses()
        
        # Verify that the test data is saved correctly
        self.assertEqual(len(expenses), 2)
        self.assertIn({"amount": 100.00, "category": "Food"}, expenses)
        self.assertIn({"amount": 50.00, "category": "Transportation"}, expenses)
        
        # Clean up by deleting the test file
        import os
        os.remove("expenses.json")

if __name__ == '__main__':
    unittest.main()
