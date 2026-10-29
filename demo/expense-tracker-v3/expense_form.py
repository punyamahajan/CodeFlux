import streamlit as st

def render_expense_form(expenses, on_submit):
    st.text("Add a new expense")
    amount = st.number_input("Amount:", value=0.0)
    category = st.text_input("Category:")
    if st.button("Add", type="primary") and amount > 0 and category:
        expenses.append({"amount": amount, "category": category})
        on_submit()
