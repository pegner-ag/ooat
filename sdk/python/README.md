# ooat-client

A client for the REST API of `ooat serve` and a reference chat bridge, for bots and scripts. Standard library only,
Python 3.12+. Not on PyPI yet: install it from a checkout with `pip install -e sdk/python`.

```python
from ooat_client import OoatClient

client = OoatClient("http://127.0.0.1:8765", token)  # from `ooat tokens create`; keep it in your secret store
task = client.submit(project="docs", goal="Summarise the contract.", acceptance=["At most 300 words."])
for event in client.follow(task):                     # the task's timeline, until TASK_CLOSED
    print(event["type"])
```

For the reception (design 08), `client.send_message(project=..., text=...)` returns `{conversation, message}` at
once, and the decision comes on `client.follow_conversation(conversation)`, with its reply, buttons and the task it
started. `client.tap(conversation, "yes")` presses a button. `client.memory(scope)`, `client.forget(scope, mem)`
and `client.done(scope, mem)` read project memory, forget an item and mark an open point done. A chat bot uses
`Bridge.converse(text, message_id)` for a message, runs `Bridge.follow(conversation)` in a thread to post the
replies, and sets `bridge.on_task` to start `watch` for each task the reception starts.

`client.revert(task)` writes back the originals of the project files a closed task changed (design 07); ask the
operator to confirm before calling it. `Bridge` posts a task's diff with its result and offers revert with a
second tap.

The chat bridge contract and `ooat_client.Bridge`: [`docs/chat-bridge.md`](../../docs/chat-bridge.md).
