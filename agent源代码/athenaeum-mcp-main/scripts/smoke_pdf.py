"""Verify the improved multi-source full-text reader against real papers."""
import asyncio
import json

from athenaeum_mcp import service
from athenaeum_mcp.http_client import close_client


async def show(label, ident):
    print(f"\n=== {label}: {ident} ===")
    r = await service.read_pdf(ident, max_chars=400)
    print("  ok:", r.get("ok"), "| source:", r.get("source"), "| pages:", r.get("pages_read"), "/", r.get("pages_total"))
    if r.get("ok"):
        print("  text:", (r["text"][:160]).replace("\n", " "))
    else:
        print("  error:", r.get("error"))
    print("  attempts:")
    for a in r.get("attempts", []):
        extra = f" -> {a['resolved_pdf_url']}" if a.get("resolved_pdf_url") else ""
        print(f"    - [{a['source']}] {a['result']}{extra}")


async def main():
    # 1. MDPI / Cloudflare — expect graceful failure with full attempt log.
    await show("MDPI Molino (Cloudflare-blocked)", "10.3390/su12155911")
    # 2. Springer — expect success via citation_pdf_url or direct.
    await show("Springer Upadhyaya", "10.1007/s10639-020-10319-9")
    # 3. arXiv — always accessible.
    await show("arXiv preprint", "arXiv:2311.07072")
    # 4. A green-OA paper with repository copies (Tarafdar ISJ).
    await show("Wiley ISJ (repo fallback)", "10.1111/isj.12253")
    await close_client()
    print("\nDONE")


if __name__ == "__main__":
    asyncio.run(main())
