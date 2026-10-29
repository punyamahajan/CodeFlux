import streamlit as st

def render_category_totals(expenses):
    if expenses:
        totals = {"Total": 0}
        for expense in expenses:
            category = expense["category"]
            amount = expense["amount"]
            if category not in totals:
                totals[category] = 0
            totals[category] += amount
            totals["Total"] += amount
        for category, total in totals.items():
            st.metric(label=category + ":", value=f"${total:.2f}", delta=None)
    else:
        st.write("No expenses to display.")
