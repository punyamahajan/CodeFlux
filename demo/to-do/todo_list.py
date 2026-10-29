from pathlib import Path

import streamlit as st

from backend import TodoStore

st.set_page_config(page_title="To-do list", page_icon=":material/checklist:")
store = TodoStore(Path(__file__).parent / "todos.json")


def toggle(todo_id: str) -> None:
    store.set_completed(todo_id, st.session_state[f"todo_{todo_id}"])


st.title("To-do list", icon=":material/checklist:")

with st.form("add_todo", clear_on_submit=True, border=False):
    with st.container(horizontal=True, vertical_alignment="bottom"):
        new_task = st.text_input("New task", placeholder="What needs doing?")
        submitted = st.form_submit_button("Add", type="primary", icon=":material/add:")
if submitted:
    try:
        store.add(new_task)
    except ValueError as exc:
        st.error(str(exc))

open_count = sum(not todo["completed"] for todo in store.todos)
with st.container(horizontal=True):
    st.metric("Open", open_count, border=True)
    st.metric("Done", len(store.todos) - open_count, border=True)

view = st.segmented_control("Show", ["All", "Open", "Done"], default="All", label_visibility="collapsed") or "All"
visible = [
    todo for todo in store.todos
    if view == "All" or (view == "Done") == todo["completed"]
]

if not store.todos:
    st.info("Nothing to do yet. Add your first task above.", icon=":material/lightbulb:")
elif not visible:
    st.caption(f"No {view.lower()} tasks.")

for todo in visible:
    # The file is the source of truth; reset the widget from it on every run.
    st.session_state[f"todo_{todo['id']}"] = todo["completed"]
    with st.container(horizontal=True, vertical_alignment="center"):
        label = f":green[~~{todo['task']}~~]" if todo["completed"] else todo["task"]
        st.checkbox(label, key=f"todo_{todo['id']}", on_change=toggle, args=(todo["id"],), width="stretch")
        st.button(
            "Delete", icon=":material/delete:", key=f"delete_{todo['id']}", type="tertiary",
            on_click=store.delete, args=(todo["id"],),
        )

if len(store.todos) - open_count:
    st.button("Clear completed", icon=":material/clear_all:", on_click=store.clear_completed)
