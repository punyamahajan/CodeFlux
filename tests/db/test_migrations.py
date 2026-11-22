from __future__ import annotations

import asyncio
from pathlib import Path

from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from codeflux.settings import Settings


def _run_alembic_sync(cmd_name: str, revision: str, url: str) -> None:
    ini_path = str(Path(__file__).parents[2] / "alembic.ini")
    cfg = Config(ini_path)
    cfg.set_main_option("sqlalchemy.url", url)
    if cmd_name == "upgrade":
        command.upgrade(cfg, revision)
    elif cmd_name == "downgrade":
        command.downgrade(cfg, revision)


async def test_alembic_migration_round_trip():
    settings = Settings()
    url = settings.database_url

    # Run in a worker thread so asyncio.run inside alembic/env.py has its own loop
    await asyncio.to_thread(_run_alembic_sync, "downgrade", "base", url)
    await asyncio.to_thread(_run_alembic_sync, "upgrade", "head", url)

    # Verify that all 11 tables exist in the database
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
        expected_tables = {
            "orgs",
            "users",
            "provider_credentials",
            "platform_keys",
            "routes",
            "limit_requests",
            "credit_ledger",
            "request_traces",
            "sessions",
            "session_messages",
            "arena_runs",
        }
        for table in expected_tables:
            assert table in tables, f"Table {table} missing from migrated database"

        # Verify indexes
        trace_indexes = await conn.run_sync(
            lambda sync_conn: {
                idx["name"] for idx in inspect(sync_conn).get_indexes("request_traces")
            }
        )
        assert "ix_request_traces_org_id_created_at" in trace_indexes

        ledger_indexes = await conn.run_sync(
            lambda sync_conn: {
                idx["name"] for idx in inspect(sync_conn).get_indexes("credit_ledger")
            }
        )
        assert "ix_credit_ledger_key_id_created_at" in ledger_indexes

    await engine.dispose()
