import streamlit as st
from ui import create_expense_category_dialog_func, create_expense_amount_input, submit_expense_amount, create_expenses_table

def main():
    category = create_expense_category_dialog_func([])
    amount = create_expense_amount_input(category)
    submit_button = st.expander("Submit Expense")
    with submit_button:
        submit = st.button('Submit')
    if submit:
        submit_expense_amount(amount, category)
    create_expenses_table(category, 'expenses.json')

main()
