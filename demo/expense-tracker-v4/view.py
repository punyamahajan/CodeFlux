import streamlit as st
from controller import calculate_totals, add_expense

def display_form():
    with st.form(key="expense_form"):
        st.number_input("Amount", min_value=0.01, key="expense_amount_form")
        st.text_input("Category", key="expense_category_form")
        if st.form_submit_button("Add Expense"):
            add_expense(st.session_state['expense_amount_form'], st.session_state['expense_category_form'])

def display_expenses_by_category():
    total_expenses = calculate_totals()
    st.write("Total Expenses by Category:")
    st.dataframe(total_expenses)
