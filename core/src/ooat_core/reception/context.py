"""What the reception sees besides the messages (design 08 §5; plan 08a decision 5), within a budget.

Sections, each item tagged with its id so a decision records what it used: the operator's preferences, the project's
instructions (CLAUDE.md, AGENTS.md, read through the workspace guard), project memory and open points, summaries of
earlier conversations, work in progress, the conversation so far with its latest numbered options, and the projects
a `switch` may name. Only items at or below the call's data class are included, so memory never raises the class of
a call nor reaches a route that may not see it. Over the budget, older summaries go first, then older turns, then
unpinned memory, then the project's instructions; preferences, open points, work in progress and the last 4 turns
always stay.
"""

from dataclasses import dataclass, field

from .. import conversations, memory
from ..pii import ORDER, raised_class
from ..state import task_state
from ..workspace.guard import Refused

INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md")
INSTRUCTION_CHARS = 4000
TURN_CHARS = 600
KEPT_TURNS = 4
MAX_TURNS = 16
MAX_SUMMARIES = 3
CLOSED = frozenset({"CLOSED_DONE", "CLOSED_PARTIAL", "CLOSED_ABSTAINED", "CANCELLED"})


@dataclass
class Context:
    text: str
    ids: list[str] = field(default_factory=list)


def _within(data_class: str, cap: str) -> bool:
    return ORDER.index(data_class) <= ORDER.index(cap)


def instructions(workspaces, conversation: str, project: str, data_class: str) -> str:
    """The project's CLAUDE.md and AGENTS.md, read through the guard; empty when there are none, the project has no
    folders, or the text would raise the call's class."""
    if workspaces is None or workspaces.project(project) is None:
        return ""
    try:
        from ..workspace.guard import Guard
        guard = Guard(workspaces.answer_grant(conversation, "context", project, 1))
    except ValueError:  # a folder is missing: the call itself says so if it needs the files
        return ""
    parts = []
    for name, _ in guard.grant.folders:
        for file in INSTRUCTION_FILES:
            try:
                shown, real = guard.resolve(f"{name}/{file}")
                if real.is_file():
                    parts.append(f"{shown}:\n{real.read_bytes()[:INSTRUCTION_CHARS].decode('utf-8', 'replace')}")
            except (Refused, OSError):
                continue
    text = "\n\n".join(parts)[:INSTRUCTION_CHARS]
    return text if text and raised_class(data_class, text) == data_class else ""


def _task_lines(events: list[dict], tasks: list[str]) -> list[tuple[str, str]]:
    by_task: dict[str, list[dict]] = {}
    for event in events:
        if event["task"] in tasks:
            by_task.setdefault(event["task"], []).append(event)
    lines = []
    for task in tasks:
        own = by_task.get(task, [])
        submitted = next((e for e in own if e["type"] == "TASK_SUBMITTED"), None)
        if submitted is None:
            continue
        state = task_state(own)
        line = f"- {task} [{state}] {submitted['body']['goal'][:200]}"
        answered = {e["body"]["request"] for e in own if e["type"] == "HIL_RESPONSE"}
        question = next((e for e in reversed(own) if e["type"] == "HIL_REQUEST" and e["id"] not in answered), None)
        if question is not None and state not in CLOSED:
            options = ", ".join(o["id"] for o in question["body"]["options"])
            line += f"\n  Open question: {question['body']['question'][:300]} (options: {options})"
        closed = next((e for e in reversed(own) if e["type"] == "TASK_CLOSED"), None)
        if closed is not None:
            line += f"\n  Outcome: {closed['body']['summary'][:300]}"
            if closed["body"].get("missing"):
                line += f" Missing: {closed['body']['missing'][:200]}"
        lines.append((task, line))
    return lines


def _turns(own: list[dict], undecided: set[str]) -> list[tuple[str, str]]:
    turns = []
    for event in own:
        body = event["body"]
        if event["type"] == "CONVERSATION_MESSAGE" and event["id"] not in undecided:
            said = conversations.message_text(event) or f"(tapped {body['tap']})"
            turns.append((event["id"], f"Person: {said[:TURN_CHARS]}"))
        elif event["type"] in ("RECEPTION_DECIDED", "CONVERSATION_REPORTED") and body.get("reply") \
                and body.get("decision") not in conversations.REPLACED:
            label = "Report" if event["type"] == "CONVERSATION_REPORTED" else f"You ({body['decision']})"
            turns.append((event["id"], f"{label}: {body['reply'][:TURN_CHARS]}"))
    return turns[-MAX_TURNS:]


def gather(*, events: list[dict], store, workspaces, operator: str, project: str, conversation: str,
           data_class: str, projects: list[str], budget_tokens: int) -> Context:
    """The context text and the ids it used."""
    own = conversations.events_of(events, conversation)
    undecided = {e["id"] for e in conversations.undecided(own)}
    cap = data_class
    preferences = memory.items(events, store, scope=memory.OPERATOR_SCOPE, cap=cap, kinds=("preference",))
    project_items = memory.items(events, store, scope=project, cap=cap, kinds=("preference", "fact", "glossary"))
    pinned = [i for i in project_items if i.pinned]
    unpinned = [i for i in project_items if not i.pinned]
    todos = memory.items(events, store, scope=project, cap=cap, kinds=("todo",))
    summaries = memory.items(events, store, scope=project, cap=cap, kinds=("summary",))[:MAX_SUMMARIES]
    by_task: dict[str, list[dict]] = {}
    for event in events:
        if event["task"] is not None:
            by_task.setdefault(event["task"], []).append(event)
    project_tasks = [t for t, own_events in by_task.items()
                     if own_events[0]["type"] == "TASK_SUBMITTED" and own_events[0]["body"].get("project") == project]
    mine = set(conversations.tasks_of(events, conversation))
    open_tasks = [t for t in project_tasks if t in mine or task_state(by_task[t]) not in CLOSED]
    work = _task_lines(events, open_tasks[-10:])
    turns = _turns(own, undecided)
    options = conversations.last_options(own)
    guide = instructions(workspaces, conversation, project, data_class)

    def render() -> str:
        parts = []
        if preferences:
            parts += ["Operator preferences:", *(f"- {i.text}" for i in preferences)]
        if guide:
            parts += ["Project instructions (from the project's files):", guide]
        if pinned or unpinned:
            parts += ["Project memory:", *(f"- ({i.kind}) {i.text}" for i in [*pinned, *unpinned])]
        if todos:
            parts += ["Open points:", *(f"- {i.id}: {i.text}" for i in todos)]
        if summaries:
            parts += ["Earlier conversations:", *(f"- {i.text}" for i in summaries)]
        if work:
            parts += ["Tasks of this project and this conversation:", *(line for _, line in work)]
        if turns:
            parts += ["This conversation so far:", *(line for _, line in turns)]
        if options:
            parts += ["Your latest numbered options:", *(f"{n}. {text}" for n, text in enumerate(options, 1))]
        parts.append(f"Project: {project}. Configured projects: {', '.join(projects) or project}.")
        return "\n".join(parts)

    limit = budget_tokens * 4
    while len(render()) > limit:
        if summaries:
            summaries.pop()
        elif len(turns) > KEPT_TURNS:
            turns.pop(0)
        elif unpinned:
            unpinned.pop()
        elif guide:
            guide = ""
        else:
            break
    ids = [i.id for i in [*preferences, *pinned, *unpinned, *todos, *summaries]] + [t for t, _ in work] + \
          [e for e, _ in turns]
    return Context(render(), list(dict.fromkeys(ids)))
