""Regression coverage for the MCP ready/waiting startup experience (issue #4).

`fresnel mcp` is a stdio JSON-RPC server. These tests run it directly against a
fake stdin, so no Spark runtime, model, or coordinator credentials are needed.
"""

import io
import json

from fresnel import mcp_server


class _FakeStdin(io.StringIO):
def __init__(self, data="", tty=False):
super().__init__(data)
self._tty = tty

def isatty(self):
return self._tty


def test_serve_prints_an_actionable_ready_message_to_stderr_only(monkeypatch, capsys):
monkeypatch.setattr(mcp_server.sys, "stdin", _FakeStdin(""))
mcp_server.serve()
captured = capsys.readouterr()
assert "Fresnel MCP ready" in captured.err
assert "docs/workflows.md" in captured.err
assert captured.out == ""


def test_ready_message_is_identical_for_direct_terminal_and_host_startup(monkeypatch, capsys):
for is_tty in (True, False):
monkeypatch.setattr(mcp_server.sys, "stdin", _FakeStdin("", tty=is_tty))
mcp_server.serve()
captured = capsys.readouterr()
assert "Fresnel MCP ready" in captured.err
assert captured.out == ""


def test_non_tty_stdout_carries_only_protocol_traffic(monkeypatch, capsys):
request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n"
monkeypatch.setattr(mcp_server.sys, "stdin", _FakeStdin(request))
mcp_server.serve()
captured = capsys.readouterr()
lines = [line for line in captured.out.splitlines() if line.strip()]
assert len(lines) == 1
message = json.loads(lines[0])
assert message["id"] == 1
assert message["result"]["serverInfo"]["name"] == "fresnel"
assert "Fresnel MCP ready" not in captured.out
assert "Fresnel MCP ready" in captured.err


def test_tools_list_round_trips_without_spark_or_credentials(monkeypatch, capsys):
request = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/list"}) + "\n"
monkeypatch.setattr(mcp_server.sys, "stdin", _FakeStdin(request))
mcp_server.serve()
captured = capsys.readouterr()
message = json.loads(captured.out.strip())
tool_names = {tool["name"] for tool in message["result"]["tools"]}
assert "fresnel_status" in tool_names
assert "fresnel_capabilities" in tool_names
