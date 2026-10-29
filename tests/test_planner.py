import json

from codeflux.planner import MAX_TASKS, checklist_from_response


def test_plain_string_array():
    assert checklist_from_response('["Write app.py", "Write tests"]') == ["Write app.py", "Write tests"]


def test_objects_are_reduced_to_their_task_text():
    reply = json.dumps([{"Task": "Create store.py", "Files": ["store.py"]}, {"task": "Create app.py"}])
    assert checklist_from_response(reply) == ["Create store.py", "Create app.py"]


def test_non_coding_steps_and_duplicates_are_dropped():
    reply = json.dumps([
        "Install Python and pip", "Create a new project folder", "Create store.py",
        "create store.py", "Deploy to Streamlit Cloud", "Run the Streamlit app",
        "Test and debug your app", "Write test_store.py",
    ])
    assert checklist_from_response(reply) == ["Create store.py", "Write test_store.py"]


def test_plan_is_capped():
    reply = json.dumps([f"Create file_{index}.py" for index in range(20)])
    assert len(checklist_from_response(reply)) == MAX_TASKS


def test_markdown_list_fallback():
    assert checklist_from_response("1. Write app.py\n- [ ] Write tests") == ["Write app.py", "Write tests"]
