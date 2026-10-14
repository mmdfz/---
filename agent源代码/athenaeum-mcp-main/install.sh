#!/usr/bin/env bash
# ===================================================================
#  Athenaeum MCP — installer / uninstaller for macOS & Linux.
#
#  Install (project scope, auto-detected clients):
#     ./install.sh
#  Options:
#     ./install.sh --scope user
#     ./install.sh --clients vscode cursor
#     ./install.sh --project /path/to/workspace
#     ./install.sh --dry-run
#  Uninstall (embedded — removes Athenaeum from client configs):
#     ./install.sh --uninstall
#     ./install.sh --uninstall --purge     # also delete .venv and caches
# ===================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$HERE/.venv/bin/python"

# Defaults
SCOPE="project"
PROJECT="$(dirname "$HERE")"   # parent of athenaeum-mcp = your workspace
CLIENTS=()
DRYRUN=0
UNINSTALL=0
PURGE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scope) SCOPE="$2"; shift 2;;
    --project) PROJECT="$2"; shift 2;;
    --clients) shift; while [[ $# -gt 0 && "$1" != --* ]]; do CLIENTS+=("$1"); shift; done;;
    --dry-run) DRYRUN=1; shift;;
    --uninstall) UNINSTALL=1; shift;;
    --purge) PURGE=1; shift;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "Unknown option: $1" >&2; exit 2;;
  esac
done

step() { printf '\033[36m==> %s\033[0m\n' "$1"; }
ok()   { printf '\033[32m    %s\033[0m\n' "$1"; }

run_configurator() {
  [[ -x "$VENV_PY" ]] || { echo "Virtual environment missing. Run without --uninstall first." >&2; exit 1; }
  "$VENV_PY" -m athenaeum_mcp.configurator "$@"
}

# ----- Uninstall -----
if [[ $UNINSTALL -eq 1 ]]; then
  step "Uninstalling Athenaeum from client configurations"
  args=(uninstall --project "$PROJECT")
  [[ ${#CLIENTS[@]} -gt 0 ]] && args+=(--clients "${CLIENTS[@]}")
  [[ $DRYRUN -eq 1 ]] && args+=(--dry-run)
  if [[ -x "$VENV_PY" ]]; then run_configurator "${args[@]}"; else ok "no venv; nothing to run"; fi

  if [[ $PURGE -eq 1 && $DRYRUN -eq 0 ]]; then
    step "Purging virtual environment and caches"
    rm -rf "$HERE/.venv" "$HERE/.athenaeum_cache" "$PROJECT/.athenaeum_cache" 2>/dev/null || true
    ok "removed .venv and caches"
  fi
  printf '\033[32m\nUninstall complete.\033[0m\n'
  exit 0
fi

# ----- Install -----
step "Athenaeum MCP installer"
echo "    project root : $PROJECT"
echo "    scope        : $SCOPE"

find_python() {
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then
      if "$c" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
        echo "$c"; return 0
      fi
    fi
  done
  return 1
}

if [[ ! -x "$VENV_PY" ]]; then
  BASE_PY="$(find_python)" || { echo "Python 3.10+ not found. Install it and re-run." >&2; exit 1; }
  step "Creating virtual environment (.venv)"
  "$BASE_PY" -m venv "$HERE/.venv"
  ok "created"
else
  ok "virtual environment already present"
fi

step "Installing Athenaeum and dependencies (this may take a minute)"
"$VENV_PY" -m pip install --upgrade pip --quiet
"$VENV_PY" -m pip install -e "$HERE" --quiet
ok "installed"

if [[ ! -f "$HERE/.env" && -f "$HERE/.env.example" ]]; then
  cp "$HERE/.env.example" "$HERE/.env"
  ok "created .env (optional settings; safe to leave blank)"
fi

step "Configuring MCP clients"
cfg=(install --scope "$SCOPE" --project "$PROJECT")
[[ ${#CLIENTS[@]} -gt 0 ]] && cfg+=(--clients "${CLIENTS[@]}")
[[ $DRYRUN -eq 1 ]] && cfg+=(--dry-run)
run_configurator "${cfg[@]}"

printf '\033[32m\nAll done. Restart your AI client (or reload its MCP servers) to use Athenaeum.\033[0m\n'
printf '\033[32mTry asking:  "Find the most-cited papers on technostress since 2018."\033[0m\n'
printf '\033[90m\nTo remove later:  ./install.sh --uninstall   (add --purge to delete the venv)\033[0m\n'
