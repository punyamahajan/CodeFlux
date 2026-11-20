import streamlit as st
import pandas as pd

# Initialize session state to store expense records
if 'expenses' not in st.session_state:
    st.session_state.expenses = []

def calculate_balance(expenses):
    """Calculates the total balance from a list of expense dictionaries."""
    if not expenses:
        return 0.0
    return sum(item['amount'] for item in expenses)

def main():
    st.title("Expense Tracker")

    # Input form
    with st.form("expense_form", clear_on_submit=True):
        description = st.text_input("Description", placeholder="e.g., Coffee")
        amount = st.number_input("Amount", min_value=0.0, step=0.01, format="%.2f")
        
        col1, col2 = st.columns(2)
        add_btn = col1.form_submit_button("Add Expense")
        sub_btn = col2.form_submit_button("Subtract Amount")

        if add_btn:
            if description:
                st.session_state.expenses.append({"description": description, "amount": float(amount)})
            else:
                st.warning("Please enter a description.")
        elif sub_btn:
            if description:
                st.session_state.expenses.append({"description": description, "amount": -float(amount)})
            else:
                st.warning("Please enter a description.")

    # Data display
    total_balance = calculate_balance(st.session_state.expenses)
    st.metric(label="Current Balance", value=f"{total_balance:.2f}")
    
    if st.session_state.expenses:
        st.subheader("Transaction History")
        # Display as a dataframe
        df = pd.DataFrame(st.session_state.expenses)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No expenses recorded yet.")

if __name__ == "__main__":
    main()
