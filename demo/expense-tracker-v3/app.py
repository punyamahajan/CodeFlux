import streamlit as st
from expense_form import render_expense_form
from category_totals import render_category_totals
from save_load import load_expenses, save_expenses

# Initialize session state to avoid re-running code whenever the app is re-run
if "expenses" not in st.session_state:
    st.session_state.expenses = load_expenses()

# Main Streamlit app layout
st.title("Expense Tracker")

# Sidebar to add expenses
if st.sidebar.button("Add Expense"):
    render_expense_form(st.session_state.expenses, on_submit=lambda: save_expenses(st.session_state.expenses))

# Main page to display category totals
st.header("Category Totals")
render_category_totals(st.session_state.expenses)
