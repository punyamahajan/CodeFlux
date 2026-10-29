import unittest
import app

class TestMainApp(unittest.TestCase):

    def test_expense_data_loading(self):
        app.expenseTracker = []
        app.load_expenses_data()
        self.assertEqual(len(app.expenseTracker), 0)

    def test_total_amount_per_category(self):
        app.expenseTracker = [{'amount': 100, 'category': 'Food'}, {'amount': 200, 'category': 'Office'}, {'amount': 300, 'category': 'Food'}]
        app.save_expenses_data()
        categories, totals = zip(*([(expense['category'])*2] for expense in app.expenseTracker))
        categories, totals = list(categories), list(totals)
        self.assertEqual(len(set(categories)), len(totals))
