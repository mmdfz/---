"""Athenaeum setup wizard: auto-configure MCP clients (install & uninstall).

Detects installed AI coding clients and writes the correct MCP server entry for
each — VS Code (Copilot), Claude Desktop, Claude Code, Cursor, Windsurf, OpenAI
Codex, OpenCode and Gemini CLI. Every write is backed up first and is fully
reversible with ``uninstall``.

Usage (via the console scripts created on install)::

    athenaeum-setup install               # project scope (default), detected clients
    athenaeum-setup install --scope user  # user/global scope
    athenaeum-setup install --clients vscode cursor
    athenaeum-setup status
    athenaeum-setup uninstall             # remove Athenaeum from every client
    athenaeum-setup install --dry-run     # preview without writing

Or directly:  ``python -m athenaeum_mcp.configurator install``
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

SERVER_ID = "athenaeum"
RUN_ARGS = ["-m", "athenaeum_mcp.server"]

_HOME = Path.home()
_IS_WIN = platform.system() == "Windows"
_APPDATA = Path(os.getenv("APPDATA", _HOME / "AppData/Roaming")) if _IS_WIN else None


# --------------------------------------------------------------------------- #
# Client specifications
# --------------------------------------------------------------------------- #
@dataclass
class ClientSpec:
    key: str
    name: str
    shape: str                       # "mcpServers" | "vscode" | "opencode" | "codex"
    fmt: str                         # "json" | "toml"
    project_path: Callable[[Path], Path] | None
    user_path: Callable[[], Path] | None
    detect: list[Path] = field(default_factory=list)

    def path_for(self, scope: str, project_root: Path) -> Path | None:
        if scope == "project":
            return self.project_path(project_root) if self.project_path else None
        return self.user_path() if self.user_path else None

    def supports(self, scope: str) -> bool:
        return self.path_for(scope, Path.cwd()) is not None or (
            scope == "project" and self.project_path is not None
        ) or (scope == "user" and self.user_path is not None)


def _claude_desktop_user() -> Path:
    if _IS_WIN:
        return _APPDATA / "Claude/claude_desktop_config.json"
    if platform.system() == "Darwin":
        return _HOME / "Library/Application Support/Claude/claude_desktop_config.json"
    return _HOME / ".config/Claude/claude_desktop_config.json"


def _windsurf_user() -> Path:
    return _HOME / ".codeium/windsurf/mcp_config.json"


CLIENTS: list[ClientSpec] = [
    ClientSpec(
        key="vscode",
        name="VS Code (GitHub Copilot)",
        shape="vscode",
        fmt="json",
        project_path=lambda root: root / ".vscode/mcp.json",
        user_path=lambda: (_APPDATA / "Code/User/mcp.json") if _IS_WIN
        else (_HOME / "Library/Application Support/Code/User/mcp.json" if platform.system() == "Darwin"
              else _HOME / ".config/Code/User/mcp.json"),
        detect=[_HOME / ".vscode", (_APPDATA / "Code") if _IS_WIN else _HOME / ".config/Code"],
    ),
    ClientSpec(
        key="claude-code",
        name="Claude Code",
        shape="mcpServers",
        fmt="json",
        project_path=lambda root: root / ".mcp.json",
        user_path=lambda: _HOME / ".claude.json",
        detect=[_HOME / ".claude", _HOME / ".claude.json"],
    ),
    ClientSpec(
        key="claude-desktop",
        name="Claude Desktop",
        shape="mcpServers",
        fmt="json",
        project_path=None,  # user scope only
        user_path=_claude_desktop_user,
        detect=[_claude_desktop_user().parent],
    ),
    ClientSpec(
        key="cursor",
        name="Cursor",
        shape="mcpServers",
        fmt="json",
        project_path=lambda root: root / ".cursor/mcp.json",
        user_path=lambda: _HOME / ".cursor/mcp.json",
        detect=[_HOME / ".cursor"],
    ),
    ClientSpec(
        key="windsurf",
        name="Windsurf",
        shape="mcpServers",
        fmt="json",
        project_path=None,  # user scope only
        user_path=_windsurf_user,
        detect=[_HOME / ".codeium/windsurf", _HOME / ".codeium"],
    ),
    ClientSpec(
        key="codex",
        name="OpenAI Codex CLI",
        shape="codex",
        fmt="toml",
        project_path=None,  # user scope only
        user_path=lambda: _HOME / ".codex/config.toml",
        detect=[_HOME / ".codex"],
    ),
    ClientSpec(
        key="opencode",
        name="OpenCode",
        shape="opencode",
        fmt="json",
        project_path=lambda root: root / "opencode.json",
        user_path=lambda: _HOME / ".config/opencode/opencode.json",
        detect=[_HOME / ".config/opencode", _HOME / ".local/share/opencode"],
    ),
    ClientSpec(
        key="gemini",
        name="Gemini CLI",
        shape="mcpServers",
        fmt="json",
        project_path=lambda root: root / ".gemini/settings.json",
        user_path=lambda: _HOME / ".gemini/settings.json",
        detect=[_HOME / ".gemini"],
    ),
]

CLIENTS_BY_KEY = {c.key: c for c in CLIENTS}


def _force_utf8() -> None:
    """Make stdout/stderr tolerate Unicode on legacy Windows code pages.

    When output is piped on Windows the default encoding is often cp1252, which
    cannot encode the status glyphs; reconfiguring to UTF-8 with a replacement
    fallback keeps the wizard from crashing on any console.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - older/odd streams
            pass


# --------------------------------------------------------------------------- #
# Server entry builders (per shape)
# --------------------------------------------------------------------------- #
def _server_entry(shape: str, python: str) -> Any:
    if shape == "vscode":
        return {"type": "stdio", "command": python, "args": list(RUN_ARGS)}
    if shape == "opencode":
        return {"type": "local", "command": [python, *RUN_ARGS], "enabled": True}
    # default "mcpServers" shape (Claude*, Cursor, Windsurf, Gemini)
    return {"command": python, "args": list(RUN_ARGS)}


def _container_key(shape: str) -> str:
    return {"vscode": "servers", "opencode": "mcp"}.get(shape, "mcpServers")


# --------------------------------------------------------------------------- #
# JSON(C) read / write
# --------------------------------------------------------------------------- #
def _strip_jsonc(text: str) -> str:
    """Best-effort strip of // and /* */ comments and trailing commas."""
    # Remove block comments.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # Remove line comments (not inside strings — heuristic: skip lines starting with //).
    out_lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue
        # inline // after value — only strip when not within quotes (rough)
        if "//" in line:
            in_str = False
            esc = False
            cut = None
            for i, ch in enumerate(line):
                if esc:
                    esc = False
                    continue
                if ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = not in_str
                elif ch == "/" and i + 1 < len(line) and line[i + 1] == "/" and not in_str:
                    cut = i
                    break
            if cut is not None:
                line = line[:cut]
        out_lines.append(line)
    text = "\n".join(out_lines)
    # Remove trailing commas.
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return text


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    raw = path.read_text(encoding="utf-8-sig")  # tolerate a BOM
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            return json.loads(_strip_jsonc(raw))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Could not parse existing JSON at {path}: {exc}")


def _backup(path: Path) -> Path | None:
    if not path.is_file():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = path.with_suffix(path.suffix + f".athenaeum-bak-{stamp}")
    shutil.copy2(path, bak)
    return bak


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Codex TOML (text-based, comment-preserving, section-scoped)
# --------------------------------------------------------------------------- #
_CODEX_SECTION = f"[mcp_servers.{SERVER_ID}]"


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _codex_block(python: str) -> str:
    args = ", ".join(f'"{_toml_escape(a)}"' for a in RUN_ARGS)
    return f'{_CODEX_SECTION}\ncommand = "{_toml_escape(python)}"\nargs = [{args}]\n'


def _remove_codex_section(text: str) -> tuple[str, bool]:
    """Remove the [mcp_servers.athenaeum] block from TOML text."""
    lines = text.splitlines()
    out: list[str] = []
    removed = False
    i = 0
    while i < len(lines):
        if lines[i].strip() == _CODEX_SECTION:
            removed = True
            i += 1
            # skip until next section header or EOF
            while i < len(lines) and not lines[i].lstrip().startswith("["):
                i += 1
        else:
            out.append(lines[i])
            i += 1
    cleaned = "\n".join(out).rstrip("\n")
    return (cleaned + "\n" if cleaned else ""), removed


# --------------------------------------------------------------------------- #
# Core operations
# --------------------------------------------------------------------------- #
class ConfigError(Exception):
    pass


@dataclass
class OpResult:
    client: str
    path: Path | None
    action: str          # "added" | "updated" | "removed" | "absent" | "skipped" | "error"
    detail: str = ""
    backup: Path | None = None


def install_client(spec: ClientSpec, scope: str, project_root: Path, python: str, dry_run: bool) -> OpResult:
    path = spec.path_for(scope, project_root)
    if path is None:
        # Fall back to user scope for user-only clients when project requested.
        if scope == "project" and spec.user_path is not None:
            path = spec.user_path()
            scope = "user (only scope supported)"
        else:
            return OpResult(spec.name, None, "skipped", f"no {scope}-scope config location")

    try:
        if spec.fmt == "toml":
            existing = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
            cleaned, had = _remove_codex_section(existing)
            if cleaned:
                cleaned = cleaned.rstrip("\n") + "\n\n"
            new_text = cleaned + _codex_block(python)
            action = "updated" if had else "added"
            if dry_run:
                return OpResult(spec.name, path, action + " (dry-run)")
            backup = _backup(path)
            _write_text(path, new_text)
            return OpResult(spec.name, path, action, str(scope), backup)

        # JSON shapes
        data = _read_json(path)
        container = _container_key(spec.shape)
        servers = data.get(container)
        if not isinstance(servers, dict):
            servers = {}
        action = "updated" if SERVER_ID in servers else "added"
        servers[SERVER_ID] = _server_entry(spec.shape, python)
        data[container] = servers
        if spec.shape == "opencode" and "$schema" not in data:
            data = {"$schema": "https://opencode.ai/config.json", **data}
        if dry_run:
            return OpResult(spec.name, path, action + " (dry-run)")
        backup = _backup(path)
        _write_text(path, json.dumps(data, indent=2) + "\n")
        return OpResult(spec.name, path, action, str(scope), backup)
    except ConfigError as exc:
        return OpResult(spec.name, path, "error", str(exc))
    except OSError as exc:
        return OpResult(spec.name, path, "error", str(exc))


def uninstall_client(spec: ClientSpec, scope: str, project_root: Path, dry_run: bool) -> OpResult:
    path = spec.path_for(scope, project_root)
    if path is None and spec.user_path is not None:
        path = spec.user_path()
    if path is None or not path.is_file():
        return OpResult(spec.name, path, "absent", "no config file")

    try:
        if spec.fmt == "toml":
            existing = path.read_text(encoding="utf-8-sig")
            cleaned, removed = _remove_codex_section(existing)
            if not removed:
                return OpResult(spec.name, path, "absent")
            if dry_run:
                return OpResult(spec.name, path, "removed (dry-run)")
            backup = _backup(path)
            _write_text(path, cleaned)
            return OpResult(spec.name, path, "removed", "", backup)

        data = _read_json(path)
        container = _container_key(spec.shape)
        servers = data.get(container)
        if not isinstance(servers, dict) or SERVER_ID not in servers:
            return OpResult(spec.name, path, "absent")
        if dry_run:
            return OpResult(spec.name, path, "removed (dry-run)")
        backup = _backup(path)
        del servers[SERVER_ID]
        if not servers:
            data.pop(container, None)
        _write_text(path, json.dumps(data, indent=2) + "\n")
        return OpResult(spec.name, path, "removed", "", backup)
    except (ConfigError, OSError) as exc:
        return OpResult(spec.name, path, "error", str(exc))


# --------------------------------------------------------------------------- #
# Detection & selection
# --------------------------------------------------------------------------- #
def is_detected(spec: ClientSpec) -> bool:
    return any(p.exists() for p in spec.detect)


def resolve_python(explicit: str | None) -> str:
    if explicit:
        return str(Path(explicit).resolve())
    return str(Path(sys.executable).resolve())


def select_clients(names: list[str] | None) -> list[ClientSpec]:
    if not names:
        return [c for c in CLIENTS if is_detected(c)]
    if len(names) == 1 and names[0].lower() == "all":
        return list(CLIENTS)
    chosen = []
    for n in names:
        spec = CLIENTS_BY_KEY.get(n.lower())
        if spec is None:
            raise ConfigError(f"Unknown client '{n}'. Valid: {', '.join(CLIENTS_BY_KEY)} (or 'all').")
        chosen.append(spec)
    return chosen


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_results(results: list[OpResult]) -> None:
    icon = {"added": "[+]", "updated": "[~]", "removed": "[-]", "absent": "[.]",
            "skipped": "[>]", "error": "[x]"}
    for r in results:
        mark = next((v for k, v in icon.items() if r.action.startswith(k)), "[*]")
        line = f"  {mark} {r.client:24} {r.action}"
        if r.path:
            line += f"  -> {r.path}"
        print(line)
        if r.detail and (r.action.startswith("error") or r.action.startswith("skipped")):
            print(f"       {r.detail}")
        if r.backup:
            print(f"       backup: {r.backup.name}")


def cmd_status(args: argparse.Namespace) -> int:
    project_root = Path(args.project).resolve()
    print(f"Athenaeum - client status (project root: {project_root})\n")
    for spec in CLIENTS:
        detected = "detected" if is_detected(spec) else "not detected"
        scopes = []
        if spec.project_path:
            scopes.append("project")
        if spec.user_path:
            scopes.append("user")
        installed_in = []
        for scope in ("project", "user"):
            path = spec.path_for(scope, project_root)
            if path and path.is_file():
                try:
                    if spec.fmt == "toml":
                        if _CODEX_SECTION in path.read_text(encoding="utf-8-sig"):
                            installed_in.append(scope)
                    else:
                        data = _read_json(path)
                        if SERVER_ID in (data.get(_container_key(spec.shape)) or {}):
                            installed_in.append(scope)
                except Exception:  # noqa: BLE001
                    pass
        star = f"  [Athenaeum installed: {', '.join(installed_in)}]" if installed_in else ""
        print(f"  {spec.name:24} {detected:13} scopes: {', '.join(scopes):14}{star}")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    project_root = Path(args.project).resolve()
    python = resolve_python(args.python)
    try:
        specs = select_clients(args.clients)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if not specs:
        print("No MCP clients detected. Specify clients explicitly, e.g.:")
        print("  athenaeum-setup install --clients vscode cursor")
        print(f"\nKnown clients: {', '.join(CLIENTS_BY_KEY)}")
        return 1

    _verify_python(python)

    print(f"Athenaeum setup - {'DRY RUN' if args.dry_run else 'install'} ({args.scope} scope)")
    print(f"  python : {python}")
    print(f"  project: {project_root}\n")

    results = [install_client(s, args.scope, project_root, python, args.dry_run) for s in specs]
    _print_results(results)

    wrote = [r for r in results if r.action.split()[0] in {"added", "updated"}]
    if wrote and not args.dry_run:
        print(f"\nDone. Athenaeum configured for {len(wrote)} client(s).")
        print("Restart the client (or reload its MCP servers) to pick up the change.")
        _maybe_env_hint(project_root)
    elif args.dry_run:
        print("\nDry run complete - no files were modified.")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    project_root = Path(args.project).resolve()
    # Uninstall everywhere by default (both scopes, all clients) unless narrowed.
    try:
        specs = select_clients(args.clients) if args.clients else list(CLIENTS)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    scopes = [args.scope] if args.scope_explicit else ["project", "user"]
    print(f"Athenaeum setup - {'DRY RUN ' if args.dry_run else ''}uninstall (scopes: {', '.join(scopes)})\n")
    results: list[OpResult] = []
    for spec in specs:
        for scope in scopes:
            if spec.path_for(scope, project_root) is None and not (scope == "user" and spec.user_path):
                continue
            results.append(uninstall_client(spec, scope, project_root, args.dry_run))
    # Collapse "absent" duplicates for readability.
    _print_results([r for r in results if not (r.action == "absent")] or results)
    removed = [r for r in results if r.action.startswith("removed")]
    if removed and not args.dry_run:
        print(f"\nDone. Removed Athenaeum from {len(removed)} config location(s). Backups were created.")
    elif not removed:
        print("\nAthenaeum was not found in any client configuration.")
    return 0


def _verify_python(python: str) -> None:
    p = Path(python)
    if not p.exists():
        print(f"Warning: python executable not found at {python}", file=sys.stderr)


def _maybe_env_hint(project_root: Path) -> None:
    env = Path(__file__).resolve().parents[2] / ".env"
    if not env.is_file():
        print("\nTip: optional settings (email for faster rate limits, Zotero, Semantic Scholar)")
        print(f"     can be placed in {env} - copy .env.example to .env. Nothing is required.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="athenaeum-setup",
        description="Configure (or remove) the Athenaeum MCP server across AI coding clients.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", default=str(Path.cwd()),
                        help="Project root for project-scope config (default: current directory).")
    common.add_argument("--clients", nargs="*",
                        help="Clients to target (keys or 'all'). Default: auto-detected clients.")
    common.add_argument("--python", default=None,
                        help="Python executable the client should launch (default: this interpreter).")
    common.add_argument("--dry-run", action="store_true", help="Preview changes without writing.")

    pi = sub.add_parser("install", parents=[common], help="Install Athenaeum into clients.")
    pi.add_argument("--scope", choices=["project", "user"], default="project",
                    help="Config scope (default: project).")
    pi.set_defaults(func=cmd_install)

    pu = sub.add_parser("uninstall", parents=[common], help="Remove Athenaeum from clients.")
    pu.add_argument("--scope", choices=["project", "user"], default=None,
                    help="Limit to one scope (default: both project and user).")
    pu.set_defaults(func=cmd_uninstall)

    ps = sub.add_parser("status", help="Show detection and install status for each client.")
    ps.add_argument("--project", default=str(Path.cwd()))
    ps.set_defaults(func=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    # Normalize uninstall scope handling.
    if args.command == "uninstall":
        args.scope_explicit = args.scope is not None
        args.scope = args.scope or "project"
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
