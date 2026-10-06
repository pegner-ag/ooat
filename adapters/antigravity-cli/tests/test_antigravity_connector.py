import json
import os
from pathlib import Path

import pytest

import ooat_adapter_antigravity_cli as adapter
from ooat_adapter_antigravity_cli import MANIFEST, AntigravityConnector, parse_stream
from ooat_core.connectors import ConnectorError, ModelRequest
from ooat_core.connectors.cli import CliResult
from ooat_core.connectors.conformance import check_connector
from ooat_core.connectors.registry import Registry

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_conformance():
    check_connector(AntigravityConnector(executable="agy-not-installed"))


def test_entry_point_is_registered():
    assert isinstance(Registry.discover().get("prv.google.subscription_cli"), AntigravityConnector)


def test_manifest_states_training_and_leaves_unknowns_null():
    assert MANIFEST["data_policy"]["training_on_inputs"] is True
    assert MANIFEST["jurisdiction"]["training_on_inputs"] is True
    assert MANIFEST["data_policy"]["allowed_data_classes"] == ["public", "internal"]
    assert MANIFEST["automation_permitted"] == "unknown"
    assert MANIFEST["jurisdiction"]["verified_on"] is None and MANIFEST["jurisdiction"]["vendor_entity"] is None
    assert MANIFEST["tiers"] == {"economy": "gemini-3.8-flash-low", "workhorse": "gemini-3.8-flash-high",
                                 "frontier": "gemini-3.1-pro-high"}


def test_recorded_success_is_parsed():
    response = parse_stream(fixture("success.jsonl"), "", 0, "gemini-3.8-flash-low")
    assert response.text.strip() == "OK"
    assert response.model == "gemini-3.8-flash-low" and response.metering == "reported"
    assert response.tokens_in > 0 and response.tokens_out >= 1 and response.tokens_cached >= 0


def test_a_denied_tool_gives_an_empty_answer_not_an_error():
    response = parse_stream(fixture("denied_tool.jsonl"), "jetski: no output produced - a tool required the "
                            "\"command\" permission", 0, "gemini-3.8-flash-low")
    assert response.text == ""  # the output check counts it as an empty attempt; the task does not pause


@pytest.mark.parametrize("name, code", [("auth_error_synthetic.jsonl", "UNAVAILABLE"),
                                        ("quota_synthetic.jsonl", "QUOTA_EXHAUSTED")])
def test_error_results_are_typed(name, code):
    with pytest.raises(ConnectorError) as info:
        parse_stream(fixture(name), "", 1, "gemini-3.8-flash-low")
    assert info.value.code == code


def test_non_json_lines_and_init_are_ignored():
    stream = 'Fetching...\n{"event":"init","init":{"tools":["view_file"]}}\n' + fixture("success.jsonl")
    assert parse_stream(stream, "", 0, "gemini-3.8-flash-low").text.strip() == "OK"


def test_output_without_a_result_is_an_api_error():
    with pytest.raises(ConnectorError) as info:
        parse_stream('{"event":"step_update","step_update":{}}\n', "panic: crashed", 2, "gemini-3.8-flash-low")
    assert info.value.code == "API_ERROR" and "crashed" in info.value.message


def test_a_rate_limit_word_on_stderr_without_a_result_is_not_a_quota_cool_down():
    with pytest.raises(ConnectorError) as info:
        parse_stream("", "warning: rate limit config ignored; crashed", 1, "gemini-3.8-flash-low")
    assert info.value.code == "API_ERROR"


def test_a_missing_login_without_a_result_is_unavailable():
    with pytest.raises(ConnectorError) as info:
        parse_stream("", "Error: authentication required", 1, "gemini-3.8-flash-low")
    assert info.value.code == "UNAVAILABLE"


def test_login_words_inside_other_words_are_not_a_login_error():
    line = '{"event":"result","result":{"status":"ERROR","error":"catalogin service failed"}}'
    with pytest.raises(ConnectorError) as info:
        parse_stream(line, "", 1, "gemini-3.8-flash-low")
    assert info.value.code == "API_ERROR"


def test_thinking_tokens_count_as_output():
    line = ('{"event":"result","result":{"status":"SUCCESS","response":"Hi","usage":{"input_tokens":100,'
            '"output_tokens":5,"thinking_tokens":40,"cache_read_tokens":30,"total_tokens":145}}}')
    response = parse_stream(line, "", 0, "gemini-3.8-flash-high")
    assert response.tokens_out == 45 and response.tokens_cached == 30
    assert response.tokens_in == (70 if adapter.INPUT_INCLUDES_CACHE else 100)
