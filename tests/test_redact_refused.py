"""scripts/redact-refused.py: a write the sandbox guard refused is never published (the review of PR 8).

The script is imported from its file and run on throwaway recordings: no process, no network.
"""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "redact-refused.py"
PLACEHOLDER = "<not published: the sandbox guard refused this write>"


@pytest.fixture(scope="module")
def rr():
    spec = importlib.util.spec_from_file_location("redact_refused", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _use(tid, content):
    return {"type": "tool_use", "tool_id": tid, "tool_name": "write_file",
            "parameters": {"path": "x.md", "content": content}}


def _result(tid, error):
    return {"type": "tool_result", "tool_id": tid, "status": "error", "error": error}


def _write(tmp_path, events):
    f = tmp_path / "run.jsonl"
    text = "".join((e if isinstance(e, str) else json.dumps(e)) + "\n" for e in events)
    f.write_text(text, encoding="utf-8")
    return f


@pytest.mark.parametrize("reason", [
    "sandbox guard: refused: Bob's own configuration (its settings, policy or gateway) is off-limits",
    "sandbox guard: tool guard error (ValueError); refusing",
    # a recording made before the marker existed
    "write refused: the content carries identifying data (masked)",
])
def test_every_kind_of_refusal_is_redacted(rr, tmp_path, reason):
    f = _write(tmp_path, [_use("t1", "marker-content"), _result("t1", reason)])
    rr.main(str(f))
    text = f.read_text(encoding="utf-8")
    assert "marker-content" not in text and PLACEHOLDER in text


def test_raw_line_separators_inside_a_string_do_not_split_an_event(rr, tmp_path):
    """JSON leaves U+2028, U+2029 and U+0085 raw; str.splitlines() would split one event into two."""
    msg = '{"type":"message","role":"assistant","content":"a b c\u0085d"}'
    refusal = _result("t1", "sandbox guard: write refused: x")
    f = _write(tmp_path, [msg, _use("t1", "marker-content"), refusal])
    rr.main(str(f))
    lines = f.read_text(encoding="utf-8").split("\n")
    assert lines[0] == msg and len(lines) == 4                 # three events and the final newline
    assert all(json.loads(x) for x in lines if x)


def test_an_odd_tool_id_does_not_crash_the_publish_step(rr, tmp_path):
    f = _write(tmp_path, [{"type": "tool_use", "tool_id": ["x"], "tool_name": "write_file", "parameters": {}},
                          {"type": "tool_result", "tool_id": {"y": 1}, "status": "error",
                           "error": "sandbox guard: x"},
                          {"type": "tool_use", "tool_id": "t2", "parameters": ["not", "a", "dict"]},
                          _result("t2", "sandbox guard: write refused: x")])
    rr.main(str(f))                                              # no TypeError, no crash


def test_nothing_refused_leaves_the_file_untouched(rr, tmp_path):
    f = _write(tmp_path, [_use("t1", "kept"), {"type": "tool_result", "tool_id": "t1", "status": "success"}])
    before, stamp = f.read_bytes(), f.stat().st_mtime_ns
    rr.main(str(f))
    assert f.read_bytes() == before
    assert f.stat().st_mtime_ns == stamp          # not even rewritten with the same bytes


# --- allowlist redaction (Oracle review of PR #47): every leak the Oracle crafted stays out ---

def _refused(tmp_path, params, reason="sandbox guard: write refused: the content carries identifying data"):
    use = {"type": "tool_use", "tool_id": "t9", "tool_name": "write_file", "parameters": params}
    return _write(tmp_path, [use, _result("t9", reason)])


@pytest.mark.parametrize("params", [
    {"path": "a.md", "files": [{"path": "b.md", "content": "LEAKMARK"}]},   # nested content
    {"path": "a.md", "Content": "LEAKMARK"},                                # case
    {"path": "a.md", "body": "LEAKMARK"},                                   # a key no list names
    {"command": "cat > ../x <<EOF\nLEAKMARK\nEOF"},                          # refused command text
    {"path": "a.md", "content": "LEAKMARK", "edits": [{"new": "LEAKMARK"}]},
])
def test_refused_call_publishes_only_tool_name_and_paths(rr, tmp_path, params):
    f = _refused(tmp_path, params)
    rr.main(str(f))
    text = f.read_text(encoding="utf-8")
    assert "LEAKMARK" not in text
    use = json.loads(text.split("\n")[0])
    assert use["tool_name"] == "write_file"
    if "path" in params:
        assert use["parameters"]["path"] == "a.md"          # an in-repo path stays readable


def test_a_path_refusal_masks_the_path_itself(rr, tmp_path):
    f = _refused(tmp_path, {"path": "/home/someone/clients/LEAKMARK.pdf", "content": "x"},
                 reason="sandbox guard: path refused: outside the repository")
    rr.main(str(f))
    assert "LEAKMARK" not in f.read_text(encoding="utf-8")


def test_path_keys_match_the_guard(rr):
    import ast
    guard = Path(__file__).resolve().parents[1] / ".bob" / "hooks" / "tool_guard.py"
    for node in ast.parse(guard.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and "PATH_KEYS" in [getattr(t, "id", None) for t in node.targets]:
            assert set(ast.literal_eval(node.value)) == set(rr.PATH_KEYS)
            return
    raise AssertionError("no PATH_KEYS in tool_guard.py")
