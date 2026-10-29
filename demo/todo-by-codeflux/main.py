import streamlit as st
import json
import os

# Function to load tasks from JSON file
def load_tasks():
    try:
        with open("tasks.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

# Function to save tasks to JSON file
def save_tasks(tasks):
    with open("tasks.json", "w") as f:
        json.dump(tasks, f)

# Function to delete a task
def delete_task(task_id):
    tasks = load_tasks()
    if "id" in tasks and str(task_id) in [str(task_id) for task_id in tasks.keys()]:
        task_id = int(task_id)  # Convert task_id to integer
        if task_id in tasks:
            if "done" in tasks[task_id]:
                del tasks[task_id]["done"]
            else:
                del tasks[task_id]
            save_tasks(tasks)

# Function to mark a task as done
def mark_task_done(task_id):
    tasks = load_tasks()
    if "id" in tasks and str(task_id) in [str(task_id) for task_id in tasks.keys()]:
        task_id = int(task_id)  # Convert task_id to integer
        if task_id in tasks:
            tasks[task_id]["done"] = True
            save_tasks(tasks)

# Function to add a new task
def add_task(task):
    tasks = load_tasks()
    if "new_task" not in tasks:
        tasks["new_task"] = {}
    if 'id' not in tasks['new_task']:
        tasks["new_task"]["id"] = len(tasks) + 1
    tasks["new_task"]["text"] = task
    save_tasks(tasks)
    return tasks

# Main app function
def main():
    tasks = load_tasks()

    # Display tasks
    st.title("To-Do App")
    st.write("Tasks:")
    for task_id, task in tasks["new_task"].items():
        if str(task_id) in [str(task_id) for task_id in tasks.keys()]:
            if "done" in tasks[str(task_id)]:
                st.write(f"[x] {task}")
            else:
                st.write(f"- {task}")

    # Input field to add new tasks
    user_input = st.text_input("Enter new task:")
    if user_input:
        add_task(user_input)

    # Button to delete tasks
    st.write("Delete Task:")
    task_ids = [str(task_id) for task_id in tasks.keys() if 'id' in tasks[task_id]]
    if task_ids:
        chosen_task_index = st.selectbox("Select task ID", task_ids, key="task_id")
        chosen_task_id = int(chosen_task_index)
        delete_task(chosen_task_id)
    else:
        st.write("No tasks available for deletion.")

    # Button to mark tasks as done
    st.write("Mark as Done:")
    task_ids = [str(task_id) for task_id in tasks.keys() if 'id' in tasks[task_id]]
    if task_ids:
        chosen_task_index = st.selectbox("Select task ID", task_ids, key="task_id")
        chosen_task_id = int(chosen_task_index)
        mark_task_done(chosen_task_id)
    else:
        st.write("No tasks available for marking as done.")

if __name__ == "__main__":
    main()
