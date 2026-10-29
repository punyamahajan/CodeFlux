import streamlit as st
from expenses_manager import save_expenses

# Streamlit app
st.title("Expense Tracker")

# Create a form for adding expenses
with st.form(key='expense_form'):
    amount = st.number_input("Amount", min_value=0.01, step=0.01)
    category = st.text_input("Category")
    submit_button = st.form_submit_button(label='Add Expense')

# On form submission, save the expense data to file
if submit_button:
    expense_data = {"amount": amount, "category": category}
    save_expenses([expense_data])
    st.success("Expense added successfully!")
