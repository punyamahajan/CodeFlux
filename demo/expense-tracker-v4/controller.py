import json
import streamlit as st
from models import Expense
from data_manager import load_expenses, save_expenses

def setup_session_state():
    if 'expenses' not in st.session_state:
        st.session_state['expenses'] = load_expenses()

def add_expense(amount, category):
    new_expense = Expense(amount, category)
    st.session_state['expenses'].append(new_expense)
    save_expenses(st.session_state['expenses'])

def calculate_totals():
    totals = {}
    for expense in st.session_state['expenses']:
        if expense.category in totals:
            totals[expense.category] += expense.amount
        else:
            totals[expense.category] = expense.amount
    return totals
