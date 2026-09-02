import pytest

from codeflux.keys import KeyPool


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

