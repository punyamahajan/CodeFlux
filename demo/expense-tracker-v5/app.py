import streamlit as st
import data_manager

st.title("Expense Tracker")

# Form to input new expenses
with st.form("expense_form", clear_on_submit=True):
    amount = st.number_input("Amount", min_value=0.0, step=0.01)
    category = st.text_input("Category")
    submitted = st.form_submit_button("Add Expense")

    if submitted:
        if amount > 0 and category:
            data_manager.add_expense(amount, category)
            st.success(f"Added {category}: ${amount:.2f}")
        else:
            st.error("Please enter a valid amount and category.")

# Display existing expenses
st.subheader("Current Expenses")
expenses = data_manager.load_expenses()
if expenses:
    st.table(expenses)
else:
    st.write("No expenses recorded yet.")

# Display totals per category
st.subheader("Totals by Category")
category_totals = data_manager.calculate_category_totals(expenses)
if category_totals:
    st.table(category_totals)
else:
    st.write("No expenses recorded yet.")
