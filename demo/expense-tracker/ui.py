import streamlit as st
from app import expenseTracker

def create_expense_category_dialog(category, expenseTracker):
    expenseTracker = expenseTracker
    session_states = st.session_state  # Use the built-in session_state variable
    if 'expenseTracker' not in session_states:
        st.session_state.expenseTracker = []
    if 'current_category' not in st.session_state:
        st.session_state.current_category = None
    st.session_state.expenseTracker = expenseTracker
    st.session_state.current_category = category
    return category

def create_expense_amount_input(amount):
    amount = st.number_input('Amount', help='Expense amount')
    return amount

def submit_expense_amount(amount, category):
    new_expense = {'amount': amount, 'category': category}
    expenseTracker.append(new_expense)
    save_expenses_data_in_session()

# Fixed the issue with submit_expense_amount where it was not updating the expenses.json
def create_expenses_table(expenseTracker, expenses_json_file):
    categories = [expense['category'] for expense in expenseTracker]
    expenses_table = {}
    for category in categories:
        table_row = []
        for expense in expenseTracker:
            if expense['category'] == category:
                table_row.append((expense['amount'], expense['category']))
        expenses_table[category] = table_row
    
    for category, expenses in expenses_table.items():
        st.write(category, '\n', 'Total:', sum(expense['amount'] for expense in expenses))
        
def create_expense_category_dialog_func(expenseTracker):
    return expenseTracker

# Storing session state in a local variable before assigning it to session_state is not necessary
# The st.session_state is built-in and can be used directly
