import pytest

from codeflux.keys import KeyPool
from codeflux.storage import ClientKeyRepository, Database


class Vault:
    async def references(self, provider):
        return ["one", "two"]

    async def get(self, reference):
        return f"secret-{reference}"


@pytest.mark.asyncio
async def test_key_pool_rotates_lru():
    pool = KeyPool(Vault())
    first = await pool.select("openai")
    second = await pool.select("openai")
    third = await pool.select("openai")
    assert first[0] != second[0]
    assert third[0] == first[0]


@pytest.mark.asyncio
async def test_preferred_key_does_not_disable_shared_pool():
    pool = KeyPool(Vault())
    selected = [await pool.select("openai", "one") for _ in range(2)]
    assert {item[0] for item in selected} == {"one", "two"}


@pytest.mark.asyncio
async def test_unconfigured_preferred_key_falls_back_to_pool():
    pool = KeyPool(Vault())
    ref, key = await pool.select("openai", "nonexistent-primary")
    assert ref in {"one", "two"}
    assert key.startswith("secret-")


@pytest.mark.asyncio
async def test_corrupt_key_skipped_for_healthy_key():
    class PartialVault:
        async def references(self, provider):
            return ["corrupt", "healthy"]

        async def get(self, reference):
            return "valid-secret" if reference == "healthy" else None

    pool = KeyPool(PartialVault())
    ref, key = await pool.select("openai")
    assert ref == "healthy"
    assert key == "valid-secret"


@pytest.mark.asyncio
async def test_managed_client_keys_are_hashed_and_authenticate():
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    repository = ClientKeyRepository(database.sessions, "test-master-secret")
    raw = await repository.create("Alice", "engineering", 100_000)
    identity = await repository.authenticate(raw)
    assert raw.startswith("cf_")
    assert identity == {"id": 1, "name": "Alice", "team": "engineering", "monthly_token_limit": 100_000}
    assert await repository.authenticate("cf_wrong") is None
    assert raw not in str(await repository.list())
    await database.close()
