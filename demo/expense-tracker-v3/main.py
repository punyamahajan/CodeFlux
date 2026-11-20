import streamlit as st
from expenses import ExpenseManager
from category_totals import render_category_totals
from save_load import load_expenses, save_expenses

# Load saved data
expenses_manager = ExpenseManager()
expenses_manager.expenses = load_expenses()

# Create form for adding expenses
with st.sidebar:
    st.number_input("Amount", key="form_amount", step=0.01)
    st.text_input("Category", key="form_category")
    if st.button("Add"):
        expenses_manager.add_expense(st.session_state.form_amount, st.session_state.form_category)
        save_expenses(expenses_manager.expenses)

# Display total expenses by category
st.title("Expense Tracker")
st.header("Category Totals")
render_category_totals(expenses_manager.get_expenses())
