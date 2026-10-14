"""Check candidate names across PyPI, npm, and GitHub repos."""
import json
import urllib.request as u

NAMES = [
    "scholarly-mcp", "mcp-scholarly", "scholarly",
    "athenaeum-mcp", "athenaeum",
    "alexandria-mcp", "lyceum-mcp", "scriptorium-mcp",
    "biblos-mcp", "folio-mcp", "marginalia-mcp", "codexa-mcp",
]


def status(url: str) -> str:
    try:
        u.urlopen(u.Request(url, headers={"User-Agent": "name-check"}), timeout=15)
        return "TAKEN"
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "code", None)
        return "free" if code == 404 else f"err({code})"


def gh_count(term: str) -> str:
    try:
        url = f"https://api.github.com/search/repositories?q={term}+mcp&per_page=1"
        with u.urlopen(u.Request(url, headers={"User-Agent": "name-check"}), timeout=15) as r:
            data = json.load(r)
        return str(data.get("total_count", "?"))
    except Exception as e:  # noqa: BLE001
        return f"err({getattr(e, 'code', None)})"


for n in NAMES:
    pypi = status(f"https://pypi.org/pypi/{n}/json")
    npm = status(f"https://registry.npmjs.org/{n}")
    print(f"{n:18} PyPI={pypi:9} npm={npm}")

print("\nGitHub repo search (name + mcp):")
for term in ["athenaeum", "alexandria", "scriptorium", "lyceum", "scholarly"]:
    print(f"  {term:14} repos≈{gh_count(term)}")
