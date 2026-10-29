import streamlit as st
from streamlit import session_state
import json
import os

def load_expenses_data():
    file_path = 'expenses.json'
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            session_state.data = json.load(f)
    else:
        session_state.data = []

def save_expenses_data():
    file_path = 'expenses.json'
    with open(file_path, 'w') as f:
        json.dump(session_state.data, f)

# Added a check to avoid modifying the session data directly
def save_expenses_data_in_session():
    if not session_state.data:
        with open('expenses.json', 'w') as f:
            json.dump([], f)
    else:
        with open('expenses.json', 'w') as f:
            json.dump(session_state.data, f)

load_expenses_data()
