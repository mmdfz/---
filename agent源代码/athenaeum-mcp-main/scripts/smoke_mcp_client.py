"""End-to-end MCP stdio smoke test: launch the server and drive it as a client.

Run: python scripts/smoke_mcp_client.py
"""
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _text(result) -> str:
    parts = []
    for block in result.content:
        parts.append(getattr(block, "text", ""))
    return "\n".join(parts)


async def main():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "athenaeum_mcp.server"],
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print(f"Connected. {len(tools.tools)} tools advertised.")

            print("\n--- athenaeum_search (meta) ---")
            r = await session.call_tool("athenaeum_search", {"query": "technostress thriving at work", "limit": 3})
            print(_text(r)[:700])

            print("\n--- athenaeum_get_work ---")
            r = await session.call_tool("athenaeum_get_work", {"identifier": "10.1128/jb.175.12.3749-3756.1993", "show_abstract": False})
            print(_text(r)[:500])

            print("\n--- athenaeum_format_citation (apa) ---")
            r = await session.call_tool("athenaeum_format_citation", {"identifier": "10.1128/jb.175.12.3749-3756.1993", "style": "apa"})
            print(_text(r)[:400])

            print("\n--- athenaeum_validate_source ---")
            r = await session.call_tool("athenaeum_validate_source", {"identifier": "10.1128/jb.175.12.3749-3756.1993"})
            print(_text(r)[:600])

            print("\n--- athenaeum_read_pdf (arXiv) ---")
            r = await session.call_tool("athenaeum_read_pdf", {"identifier_or_url": "arXiv:2311.07072", "max_chars": 300})
            print(_text(r)[:400])

            print("\n--- athenaeum_get_venue (ISSN) ---")
            r = await session.call_tool("athenaeum_get_venue", {"issn_or_name": "0021-9010"})
            print(_text(r)[:400])

    print("\nMCP STDIO SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
