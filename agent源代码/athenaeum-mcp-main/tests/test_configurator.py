import json

import pytest

from athenaeum_mcp import configurator as cfg

PY = r"C:\fake\python.exe"


def _install(spec, scope, root):
    return cfg.install_client(spec, scope, root, PY, dry_run=False)


def test_vscode_shape(tmp_path):
    spec = cfg.CLIENTS_BY_KEY["vscode"]
    _install(spec, "project", tmp_path)
    data = json.loads((tmp_path / ".vscode/mcp.json").read_text())
    entry = data["servers"]["athenaeum"]
    assert entry["type"] == "stdio"
    assert entry["command"] == PY
    assert entry["args"] == ["-m", "athenaeum_mcp.server"]


def test_mcpservers_shape(tmp_path):
    spec = cfg.CLIENTS_BY_KEY["cursor"]
    _install(spec, "project", tmp_path)
    data = json.loads((tmp_path / ".cursor/mcp.json").read_text())
    entry = data["mcpServers"]["athenaeum"]
    assert "type" not in entry
    assert entry["command"] == PY


def test_opencode_shape_command_is_array(tmp_path):
    spec = cfg.CLIENTS_BY_KEY["opencode"]
    _install(spec, "project", tmp_path)
    data = json.loads((tmp_path / "opencode.json").read_text())
    entry = data["mcp"]["athenaeum"]
    assert entry["type"] == "local"
    assert entry["command"] == [PY, "-m", "athenaeum_mcp.server"]
    assert entry["enabled"] is True
    assert data["$schema"].startswith("https://opencode.ai")


def test_non_destructive_merge(tmp_path):
    vs = tmp_path / ".vscode"
    vs.mkdir()
    (vs / "mcp.json").write_text(json.dumps(
        {"servers": {"keepme": {"type": "stdio", "command": "node"}}}), encoding="utf-8")
    spec = cfg.CLIENTS_BY_KEY["vscode"]
    _install(spec, "project", tmp_path)
    data = json.loads((vs / "mcp.json").read_text())
    assert "keepme" in data["servers"]
    assert "athenaeum" in data["servers"]


def test_install_is_idempotent(tmp_path):
    spec = cfg.CLIENTS_BY_KEY["gemini"]
    r1 = _install(spec, "project", tmp_path)
    r2 = _install(spec, "project", tmp_path)
    assert r1.action == "added"
    assert r2.action == "updated"
    data = json.loads((tmp_path / ".gemini/settings.json").read_text())
    assert len(data["mcpServers"]) == 1


def test_uninstall_removes_only_athenaeum(tmp_path):
    vs = tmp_path / ".vscode"
    vs.mkdir()
    (vs / "mcp.json").write_text(json.dumps(
        {"servers": {"keepme": {"command": "node"}}}), encoding="utf-8")
    spec = cfg.CLIENTS_BY_KEY["vscode"]
    _install(spec, "project", tmp_path)
    cfg.uninstall_client(spec, "project", tmp_path, dry_run=False)
    data = json.loads((vs / "mcp.json").read_text())
    assert "athenaeum" not in data.get("servers", {})
    assert "keepme" in data["servers"]


def test_codex_toml_roundtrip(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('model = "gpt-5"\n\n[mcp_servers.other]\ncommand = "x"\n', encoding="utf-8")
    spec = cfg.CLIENTS_BY_KEY["codex"]
    spec.user_path = lambda: path
    cfg.install_client(spec, "user", tmp_path, PY, dry_run=False)
    text = path.read_text()
    assert "[mcp_servers.athenaeum]" in text
    assert "[mcp_servers.other]" in text
    assert 'model = "gpt-5"' in text
    cfg.uninstall_client(spec, "user", tmp_path, dry_run=False)
    text = path.read_text()
    assert "[mcp_servers.athenaeum]" not in text
    assert "[mcp_servers.other]" in text


def test_dry_run_writes_nothing(tmp_path):
    spec = cfg.CLIENTS_BY_KEY["cursor"]
    cfg.install_client(spec, "project", tmp_path, PY, dry_run=True)
    assert not (tmp_path / ".cursor/mcp.json").exists()


def test_jsonc_with_comments_is_parsed(tmp_path):
    vs = tmp_path / ".vscode"
    vs.mkdir()
    (vs / "mcp.json").write_text(
        '{\n  // a comment\n  "servers": {\n    "keepme": { "command": "node" },\n  }\n}',
        encoding="utf-8",
    )
    spec = cfg.CLIENTS_BY_KEY["vscode"]
    _install(spec, "project", tmp_path)
    data = json.loads((vs / "mcp.json").read_text())
    assert "keepme" in data["servers"]
    assert "athenaeum" in data["servers"]


def test_unknown_client_raises():
    with pytest.raises(cfg.ConfigError):
        cfg.select_clients(["not-a-client"])


def test_select_all_returns_every_client():
    assert len(cfg.select_clients(["all"])) == len(cfg.CLIENTS)
