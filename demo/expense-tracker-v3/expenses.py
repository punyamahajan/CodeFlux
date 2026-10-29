class ExpenseManager:
    def __init__(self):
        self.expenses = []

    def add_expense(self, amount, category):
        self.expenses.append({"amount": amount, "category": category})

    def get_expenses(self):
        return self.expenses
