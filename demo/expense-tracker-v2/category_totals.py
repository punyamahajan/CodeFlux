import json
from collections import defaultdict
import os

def calculate_category_totals():
    file_path = "expenses.json"
    category_totals = defaultdict(float)

    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            expenses = json.load(file)
            for expense in expenses:
                category = expense.get("category")
                amount = expense.get("amount")
                if category and amount:
                    category_totals[category] += amount
    return category_totals

def display_category_totals():
    st.title("Category Totals")
    category_totals = calculate_category_totals()
    if category_totals:
        st.subheader("Total Expenses by Category")
        for category, total in category_totals.items():
            st.write(f"{category}: ${total:.2f}")
    else:
        st.write("No expenses recorded yet.")

if __name__ == "__main__":
    display_category_totals()
