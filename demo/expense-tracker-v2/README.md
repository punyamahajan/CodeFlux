# Streamlit Expense Tracker

A simple expense tracker built with Streamlit.

## Prerequisites

- Python 3.8 or higher
- Streamlit

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/your_username/expense_tracker.git
   cd expense_tracker
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Running the Expense Tracker

1. Start the Streamlit app:
   ```bash
   streamlit run expenses.py
   ```

This will open the Streamlit app in your default web browser. You can add expenses by filling out the form, and the app will save the expenses to a JSON file named `expenses.json`. Additionally, you can view the total expenses per category using the category totals page.

## Testing

1. Run the unit tests to ensure the `save_expenses()` function works correctly:
   ```bash
   python -m unittest test_expenses_manager.py
   ```

This will execute the test and clean up the test file.
