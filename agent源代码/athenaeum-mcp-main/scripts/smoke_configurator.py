"""Verify configurator install/uninstall produces correct config per client shape."""
import json
import tempfile
from pathlib import Path

from athenaeum_mcp import configurator as cfg

PY = r"C:\fake\python.exe"


def show(path: Path):
    print(f"\n----- {path.name} -----")
    print(path.read_text(encoding="utf-8").rstrip())


def main():
    tmp = Path(tempfile.mkdtemp(prefix="ath_cfg_"))
    print(f"temp project: {tmp}")

    # Pre-seed a couple of files with an existing server to prove non-destructive merge.
    (tmp / ".vscode").mkdir()
    (tmp / ".vscode/mcp.json").write_text(json.dumps({
        "servers": {"existing-server": {"type": "stdio", "command": "node", "args": ["x.js"]}}
    }, indent=2), encoding="utf-8")
    (tmp / "opencode.json").write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "mcp": {"other": {"type": "local", "command": ["foo"], "enabled": True}}
    }, indent=2), encoding="utf-8")

    project_clients = ["vscode", "cursor", "opencode", "gemini", "claude-code"]
    print("\n=== INSTALL (project scope) ===")
    for key in project_clients:
        spec = cfg.CLIENTS_BY_KEY[key]
        r = cfg.install_client(spec, "project", tmp, PY, dry_run=False)
        print(f"  {r.client:24} {r.action:10} {r.path.name if r.path else '-'}")

    for key in project_clients:
        spec = cfg.CLIENTS_BY_KEY[key]
        show(spec.path_for("project", tmp))

    # Idempotency: install again, ensure still single entry + existing preserved.
    print("\n=== RE-INSTALL (idempotency check) ===")
    for key in project_clients:
        spec = cfg.CLIENTS_BY_KEY[key]
        r = cfg.install_client(spec, "project", tmp, PY, dry_run=False)
        print(f"  {r.client:24} {r.action}")
    vs = json.loads((tmp / ".vscode/mcp.json").read_text())
    assert "existing-server" in vs["servers"], "existing server lost!"
    assert "athenaeum" in vs["servers"], "athenaeum missing!"
    assert len(vs["servers"]) == 2, f"expected 2 servers, got {len(vs['servers'])}"
    oc = json.loads((tmp / "opencode.json").read_text())
    assert "other" in oc["mcp"] and "athenaeum" in oc["mcp"], "opencode merge failed"
    print("  idempotent + non-destructive: OK")

    # Codex TOML round-trip
    print("\n=== CODEX TOML ===")
    codex_path = tmp / "config.toml"
    codex_path.write_text('model = "gpt-5"\n\n[mcp_servers.other]\ncommand = "x"\n', encoding="utf-8")
    spec = cfg.CLIENTS_BY_KEY["codex"]
    # monkeypatch user_path to our temp file
    spec.user_path = lambda: codex_path
    r = cfg.install_client(spec, "user", tmp, PY, dry_run=False)
    show(codex_path)
    assert "[mcp_servers.athenaeum]" in codex_path.read_text()
    assert "[mcp_servers.other]" in codex_path.read_text(), "existing codex server lost!"
    assert 'model = "gpt-5"' in codex_path.read_text(), "codex top-level lost!"

    # Uninstall everything
    print("\n=== UNINSTALL ===")
    for key in project_clients:
        spec = cfg.CLIENTS_BY_KEY[key]
        r = cfg.uninstall_client(spec, "project", tmp, dry_run=False)
        print(f"  {r.client:24} {r.action}")
    vs = json.loads((tmp / ".vscode/mcp.json").read_text())
    assert "athenaeum" not in vs.get("servers", {}), "athenaeum not removed!"
    assert "existing-server" in vs["servers"], "existing server lost on uninstall!"
    spec = cfg.CLIENTS_BY_KEY["codex"]
    spec.user_path = lambda: codex_path
    r = cfg.uninstall_client(spec, "user", tmp, dry_run=False)
    assert "[mcp_servers.athenaeum]" not in codex_path.read_text(), "codex not removed!"
    assert "[mcp_servers.other]" in codex_path.read_text(), "codex other lost!"
    print("  uninstall preserved other servers: OK")

    print("\nALL CONFIGURATOR CHECKS PASSED")


if __name__ == "__main__":
    main()
