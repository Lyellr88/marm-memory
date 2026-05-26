"""Tests for scripts/scan-stale-docs.py changes in this PR.

Covers the six new RULES added in this PR:
- "old context log name"  (marm_contextual_log / ContextualLogRequest / contextual_log)
- "split notebook tools"  (marm_notebook_add|use|show|status|clear)
- "hidden lifecycle tools" (marm_start / marm_refresh / marm_reload_docs)
- "removed system tools"  (marm_current_context / marm_system_info)
- "old tool count"        (12/18/19 tools)
- "old command prompt framing" (copy/paste / slash command etc.)

Each new rule is tested for:
  - Match on a line containing a known stale reference
  - No false positive on a benign line that should not match
"""

import importlib.util
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load the script as a module without executing __main__
# ---------------------------------------------------------------------------
_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "scan-stale-docs.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("scan_stale_docs", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ssd():
    return _load_script()


def _rule_by_name(ssd, name: str):
    """Return the StaleRule with the given name, or fail the test."""
    for rule in ssd.RULES:
        if rule.name == name:
            return rule
    raise AssertionError(f"Rule '{name}' not found in RULES list")


# ---------------------------------------------------------------------------
# "old context log name"
# ---------------------------------------------------------------------------

def test_rule_old_context_log_name_matches_marm_contextual_log(ssd):
    rule = _rule_by_name(ssd, "old context log name")
    assert rule.pattern.search("Use `marm_contextual_log` to store context.")


def test_rule_old_context_log_name_matches_ContextualLogRequest(ssd):
    rule = _rule_by_name(ssd, "old context log name")
    assert rule.pattern.search("class ContextualLogRequest(BaseModel):")


def test_rule_old_context_log_name_matches_contextual_log_lowercase(ssd):
    rule = _rule_by_name(ssd, "old context log name")
    assert rule.pattern.search("action: contextual_log operation")


def test_rule_old_context_log_name_no_false_positive_on_context_log(ssd):
    rule = _rule_by_name(ssd, "old context log name")
    # "marm_context_log" is the correct new name — should NOT match
    assert not rule.pattern.search("Use marm_context_log to store context.")


def test_rule_old_context_log_name_no_false_positive_on_unrelated_text(ssd):
    rule = _rule_by_name(ssd, "old context log name")
    assert not rule.pattern.search("The server uses structured logging for all events.")


# ---------------------------------------------------------------------------
# "split notebook tools"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    "Call marm_notebook_add to create an entry.",
    "Use marm_notebook_use for activation.",
    "marm_notebook_show lists all saved notes.",
    "marm_notebook_status returns active count.",
    "marm_notebook_clear empties the active list.",
    "MARM_NOTEBOOK_ADD is an old tool name.",  # case-insensitive
])
def test_rule_split_notebook_tools_matches_old_tool_names(ssd, line):
    rule = _rule_by_name(ssd, "split notebook tools")
    assert rule.pattern.search(line), f"Expected match for: {line!r}"


def test_rule_split_notebook_tools_no_false_positive_on_action_param(ssd):
    rule = _rule_by_name(ssd, "split notebook tools")
    # The new API form — must NOT match
    assert not rule.pattern.search("marm_notebook(action='add')")
    assert not rule.pattern.search("marm_notebook(action='show')")


def test_rule_split_notebook_tools_no_false_positive_on_marm_notebook_alone(ssd):
    rule = _rule_by_name(ssd, "split notebook tools")
    assert not rule.pattern.search("marm_notebook is the consolidated tool.")


# ---------------------------------------------------------------------------
# "hidden lifecycle tools"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    "Call marm_start to initialize the session.",
    "Use marm_refresh to update context.",
    "marm_reload_docs reindexes all documentation.",
    "Run MARM_START before any other tool.",  # case-insensitive
])
def test_rule_hidden_lifecycle_tools_matches_lifecycle_tools(ssd, line):
    rule = _rule_by_name(ssd, "hidden lifecycle tools")
    assert rule.pattern.search(line), f"Expected match for: {line!r}"


def test_rule_hidden_lifecycle_tools_no_false_positive(ssd):
    rule = _rule_by_name(ssd, "hidden lifecycle tools")
    assert not rule.pattern.search("The server automates session startup internally.")
    assert not rule.pattern.search("Documentation is refreshed every 50 tool calls.")


# ---------------------------------------------------------------------------
# "removed system tools"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    "Use marm_current_context to inspect state.",
    "marm_system_info returns server metadata.",
    "MARM_CURRENT_CONTEXT was a public tool.",  # case-insensitive
])
def test_rule_removed_system_tools_matches_removed_names(ssd, line):
    rule = _rule_by_name(ssd, "removed system tools")
    assert rule.pattern.search(line), f"Expected match for: {line!r}"


def test_rule_removed_system_tools_no_false_positive(ssd):
    rule = _rule_by_name(ssd, "removed system tools")
    assert not rule.pattern.search("Use /health for system status.")
    assert not rule.pattern.search("Context is injected automatically on first tool call.")


# ---------------------------------------------------------------------------
# "old tool count"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    "MARM provides 12 complete MCP tools.",
    "The server exposes 18 tools for agents.",
    "Use all 19 focused MCP tools.",
    "12 tools are available out of the box.",
    "19 complete tools ship with this version.",
])
def test_rule_old_tool_count_matches_outdated_numbers(ssd, line):
    rule = _rule_by_name(ssd, "old tool count")
    assert rule.pattern.search(line), f"Expected match for: {line!r}"


def test_rule_old_tool_count_no_false_positive_on_current_count(ssd):
    rule = _rule_by_name(ssd, "old tool count")
    assert not rule.pattern.search("MARM exposes 8 public MCP tools.")


def test_rule_old_tool_count_no_false_positive_on_unrelated_numbers(ssd):
    rule = _rule_by_name(ssd, "old tool count")
    # "12" by itself with no "tools" context should not match
    assert not rule.pattern.search("Python 3.12 is supported.")
    assert not rule.pattern.search("Version 2.19 was released last year.")


# ---------------------------------------------------------------------------
# "old command prompt framing"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    "Copy/paste this prompt into Claude.",
    "Copy and paste the following command.",
    "Use the /slash command for quick access.",
    "Run the slash-command to trigger the tool.",
    "COPY/PASTE the text into the chat.",  # case-insensitive
])
def test_rule_old_command_prompt_framing_matches_stale_patterns(ssd, line):
    rule = _rule_by_name(ssd, "old command prompt framing")
    assert rule.pattern.search(line), f"Expected match for: {line!r}"


def test_rule_old_command_prompt_framing_no_false_positive(ssd):
    rule = _rule_by_name(ssd, "old command prompt framing")
    assert not rule.pattern.search("The MCP server responds to tool calls automatically.")
    assert not rule.pattern.search("Agents invoke tools using JSON-RPC.")


# ---------------------------------------------------------------------------
# RULES list completeness
# ---------------------------------------------------------------------------

def test_all_new_rules_are_present_in_rules_list(ssd):
    """Verify all six rules added in this PR appear in RULES."""
    expected = {
        "old context log name",
        "split notebook tools",
        "hidden lifecycle tools",
        "removed system tools",
        "old tool count",
        "old command prompt framing",
    }
    actual = {rule.name for rule in ssd.RULES}
    missing = expected - actual
    assert not missing, f"Missing expected rules: {missing}"


def test_rules_list_has_no_duplicates(ssd):
    names = [rule.name for rule in ssd.RULES]
    assert len(names) == len(set(names)), "RULES list has duplicate rule names"