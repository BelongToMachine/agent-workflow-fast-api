import asyncio

from app.db.knowledge_seed import run_cli

if __name__ == "__main__":
    raise SystemExit(
        asyncio.run(run_cli(("productOperations", "productPrices")))
    )
