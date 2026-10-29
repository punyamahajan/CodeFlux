import streamlit as st
from controller import setup_session_state
from view import display_form, display_expenses_by_category

def main():
    st.title("Expense Tracker")
    setup_session_state()

    display_form()
    display_expenses_by_category()

if __name__ == "__main__":
    main()
