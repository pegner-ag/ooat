"""Project memory and operator preferences: texts outside the ledger, a secret scan, forgetting for real (design 08
§6, §7; ADR 0018)."""

import json

import pytest

from ooat_core import memory
from ooat_core.ids import new_id
from ooat_core.ledger import Ledger
from ooat_core.memory import MemoryStore, SecretRefused, UnknownMemory

RECEPTION = {"kind": "system", "id": "ooat-reception"}


@pytest.fixture
def ledger():
    ledger = Ledger.open("sqlite:///:memory:")
    yield ledger
    ledger.close()


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "ooat-memory")


def noted(ledger, store, text="Ceny uvádíme s DPH.", scope="docs", kind="fact", data_class="internal", **options):
    return memory.note(ledger, store, scope=scope, kind=kind, text=text, data_class=data_class,
                       source=new_id("evt"), actor=RECEPTION, **options)


def test_a_note_keeps_its_text_out_of_the_ledger(ledger, store):
    item = noted(ledger, store)
    events = ledger.events()
    assert len(events) == 1 and "DPH" not in json.dumps(events, ensure_ascii=False)
    assert events[0]["body"]["sha256"] == memory.sha256_text("Ceny uvádíme s DPH.")
    assert store.read(item.id) == "Ceny uvádíme s DPH."


@pytest.mark.parametrize("text", [
    "heslo: Tajne123!", "password=hunter22", "Server=db;User Id=sa;Password=x1;", "-----BEGIN PRIVATE KEY-----",
    "ghp_" + "a1B2" * 9, "sk-" + "x9Y8" * 10, "ooat_" + "Q" * 40, "AKIA" + "ABCDEFGH12345678",
    "api key: 9f8e7d6c5b4a", "token = abc123def456ghi789",
])
def test_a_secret_is_never_stored(ledger, store, text):
    with pytest.raises(SecretRefused) as refused:
        noted(ledger, store, text=text)
    assert text not in str(refused.value)
    assert ledger.events() == []
    assert not store.folder.exists() or not list(store.folder.glob("*.txt"))


@pytest.mark.parametrize("text", [
    "Ceny uvádíme s DPH.", "The token budget is 2 USD per task.", "The password reset page is /reset.",
    "Odpovídej česky a stručně.", "API klíče jsou v proměnných prostředí, ne v souborech.",
])
def test_ordinary_text_is_not_a_secret(text):
    assert memory.looks_secret(text) is None


def test_personal_data_raises_the_class(ledger, store):
    item = noted(ledger, store, text="Kontakt na dodavatele je jan.novak@example.cz.")
    assert item.data_class == "personal"
    assert ledger.events()[0]["body"]["data_class"] == "personal"


def test_forgetting_deletes_the_file_and_the_item_is_gone(ledger, store):
    item = noted(ledger, store)
    memory.forget(ledger, store, item.id, operator="operator", channel="web", reason="no longer true")
    assert store.read(item.id) is None
    assert memory.items(ledger.events(), store, scope="docs") == []
    with pytest.raises(UnknownMemory):
        memory.forget(ledger, store, item.id, operator="operator", channel="web")


def test_a_missing_file_reads_as_forgotten(ledger, store):
    item = noted(ledger, store)
    store.delete(item.id)
    assert memory.items(ledger.events(), store, scope="docs") == []


def test_items_are_capped_by_class(ledger, store):
    noted(ledger, store, text="Interní fakt.")
    noted(ledger, store, text="Důvěrná cena pro klienta.", data_class="client_confidential")
    texts = [i.text for i in memory.items(ledger.events(), store, scope="docs", cap="internal")]
    assert texts == ["Interní fakt."]
    assert len(memory.items(ledger.events(), store, scope="docs")) == 2


def test_project_memory_never_crosses_projects(ledger, store):
    noted(ledger, store, scope="data-development-testdna-cz")
    assert memory.items(ledger.events(), store, scope="data-web-testdna-cz") == []


def test_twenty_preferences_at_most(ledger, store):
    for n in range(memory.MAX_PREFERENCES):
        noted(ledger, store, text=f"Preference {n}.", scope=memory.OPERATOR_SCOPE, kind="preference")
    with pytest.raises(ValueError, match="20"):
        noted(ledger, store, text="One more.", scope=memory.OPERATOR_SCOPE, kind="preference")


def test_an_edit_records_the_new_hash(ledger, store):
    item = noted(ledger, store)
    event = memory.edit(ledger, store, item.id, operator="operator", channel="web", text="Ceny uvádíme bez DPH.")
    assert event["body"]["sha256"] == memory.sha256_text("Ceny uvádíme bez DPH.")
    assert memory.items(ledger.events(), store, scope="docs")[0].text == "Ceny uvádíme bez DPH."


def test_an_edit_is_scanned_like_a_note(ledger, store):
    item = noted(ledger, store)
    with pytest.raises(SecretRefused):
        memory.edit(ledger, store, item.id, operator="operator", channel="web", text="password=hunter22")
    assert store.read(item.id) == "Ceny uvádíme s DPH."


def test_done_is_only_for_open_points(ledger, store):
    fact, todo = noted(ledger, store), noted(ledger, store, text="Na konci projektu nastavit DNS.", kind="todo")
    with pytest.raises(ValueError, match="open point"):
        memory.edit(ledger, store, fact.id, operator="operator", channel="web", done=True)
    memory.edit(ledger, store, todo.id, operator="operator", channel="web", done=True)
    assert [i.id for i in memory.items(ledger.events(), store, scope="docs")] == [fact.id]
    done = memory.items(ledger.events(), store, scope="docs", include_done=True)
    assert {i.id: i.done for i in done} == {fact.id: False, todo.id: True}


def test_pinned_items_come_first_then_the_newest(ledger, store):
    first, second = noted(ledger, store, text="První."), noted(ledger, store, text="Druhý.")
    memory.edit(ledger, store, first.id, operator="operator", channel="web", pinned=True)
    third = noted(ledger, store, text="Třetí.")
    assert [i.id for i in memory.items(ledger.events(), store, scope="docs")] == [first.id, third.id, second.id]


def test_kinds_filter(ledger, store):
    noted(ledger, store)
    todo = noted(ledger, store, text="Připomenout DNS.", kind="todo")
    assert [i.id for i in memory.items(ledger.events(), store, scope="docs", kinds=("todo",))] == [todo.id]


def test_an_unknown_kind_is_refused(ledger, store):
    with pytest.raises(ValueError, match="kind"):
        noted(ledger, store, kind="secret")


def test_a_failed_event_leaves_no_text(ledger, store, monkeypatch):
    def refuse(event, artifacts=()):
        raise ValueError("ledger refused")
    monkeypatch.setattr(ledger, "append", refuse)
    with pytest.raises(ValueError, match="ledger refused"):
        noted(ledger, store)
    assert not list(store.folder.glob("*.txt"))


def test_the_memory_folder_lies_beside_a_file_ledger(tmp_path):
    assert memory.memory_folder(f"sqlite:///{(tmp_path / 'ledger.sqlite').as_posix()}") == tmp_path / "ooat-memory"
    assert memory.memory_folder("sqlite:///:memory:") is None


def test_a_secret_scan_is_linear_on_a_long_text():
    import time
    started = time.monotonic()
    memory.looks_secret("a" * 200_000 + "=" + "b" * 200_000)
    assert time.monotonic() - started < 2
