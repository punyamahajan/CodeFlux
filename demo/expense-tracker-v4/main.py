import streamlit as st
from controller import setup_session_state, add_expense
from view import display_form, display_expenses_by_category

st.title("Expense Tracker")
setup_session_state()

display_form()
display_expenses_by_category()
