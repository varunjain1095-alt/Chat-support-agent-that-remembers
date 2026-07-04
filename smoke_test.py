"""
smoke_test.py — Phase 0 Definition of Done verification.

Verifies:
  1. config.py loads all required environment variables
  2. Claude (Anthropic) client initializes and responds
  3. Mem0 client initializes and responds
  4. Zep client initializes and responds

Run from the project root:
    python smoke_test.py
"""

import sys


def check(label: str, ok: bool, detail: str = "") -> None:
    status = "✅ PASS" if ok else "❌ FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  {status}  {label}{suffix}")
    if not ok:
        sys.exit(1)


def main() -> None:
    print("\n=== Phase 0 Smoke Test ===\n")

    # ------------------------------------------------------------------
    # 1. Config loads without errors
    # ------------------------------------------------------------------
    print("[ 1 / 4 ] Config loading ...")
    try:
        import config
        check(
            "config.py loaded",
            True,
            f"ANTHROPIC={'set' if config.ANTHROPIC_API_KEY else 'MISSING'}  "
            f"MEM0={'set' if config.MEM0_API_KEY else 'MISSING'}  "
            f"ZEP={'set' if config.ZEP_API_KEY else 'MISSING'}  "
            f"OPENAI={'set' if config.OPENAI_API_KEY else 'MISSING'}",
        )
    except EnvironmentError as exc:
        check("config.py loaded", False, str(exc))

    # ------------------------------------------------------------------
    # 2. Anthropic (Claude) client
    # ------------------------------------------------------------------
    print("\n[ 2 / 4 ] Claude API ping ...")
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=5,
            messages=[{"role": "user", "content": "Reply with the single word: OK"}],
        )
        reply = response.content[0].text.strip()
        check("Claude client initializes and responds", bool(reply), f"reply='{reply}'")
    except Exception as exc:
        check("Claude client initializes and responds", False, str(exc))

    # ------------------------------------------------------------------
    # 3. Mem0 client
    # ------------------------------------------------------------------
    print("\n[ 3 / 4 ] Mem0 API ping ...")
    try:
        from mem0 import MemoryClient
        mem0 = MemoryClient(api_key=config.MEM0_API_KEY)
        result = mem0.search(query="smoke test ping", filters={"user_id": "smoke_test_phase0"})
        ok = isinstance(result, list) or (isinstance(result, dict) and "results" in result)
        check(
            "Mem0 client initializes and responds",
            ok,
            f"returned {type(result).__name__} with {len(result)} item(s)",
        )
    except Exception as exc:
        check("Mem0 client initializes and responds", False, str(exc))

    # ------------------------------------------------------------------
    # 4. Zep client
    # ------------------------------------------------------------------
    print("\n[ 4 / 4 ] Zep API ping ...")
    try:
        from zep_cloud.client import Zep
        zep = Zep(api_key=config.ZEP_API_KEY)
        result = zep.graph.search(query="smoke test ping", user_id="smoke_test_phase0")
        check("Zep client initializes and responds", result is not None, "search call completed")
    except Exception as exc:
        check("Zep client initializes and responds", False, str(exc))

    print("\n=== All checks passed — Phase 0 complete ===\n")


if __name__ == "__main__":
    main()
