"""work.py — YOUR agent's brain. This is the only file you need to edit.

do_work receives the buyer's request body (a dict) and returns any
JSON-serializable result. Everything else — payment verification,
settlement, delivery — is handled by serve.py."""

def do_work(body: dict):
    # TODO: replace this with your agent's actual work.
    # Examples of what agents do here: call an LLM, hit an API,
    # analyze data, generate content, run a computation.
    task = body.get("task", "")
    return {
        "echo": f"You asked: {task}",
        "note": "Edit work.py — this is the placeholder response.",
    }
