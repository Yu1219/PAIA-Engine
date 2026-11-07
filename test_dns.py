"""Test different HTTP approaches to diagnose connection issue."""
import urllib.request
import ssl

# Test 1: urllib (stdlib)
print("=== Test 1: urllib (stdlib) ===")
try:
    url = "https://rest.uniprot.org/uniprotkb/search?query=accession:P04637&format=json&size=1"
    req = urllib.request.Request(url)
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        print(f"Status: {resp.status}")
        data = resp.read(200)
        print(f"Data (first 200 chars): {data[:200]}")
except Exception as e:
    print(f"Exception: {type(e).__name__}: {e}")

# Test 2: requests (if installed)
print("\n=== Test 2: requests ===")
try:
    import requests
    resp = requests.get(
        "https://rest.uniprot.org/uniprotkb/search",
        params={"query": "accession:P04637", "format": "json", "size": "1"},
        timeout=15,
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        j = resp.json()
        print(f"Results count: {len(j.get('results', []))}")
except Exception as e:
    print(f"Exception: {type(e).__name__}: {e}")

# Test 3: aiohttp with ThreadedResolver
print("\n=== Test 3: aiohttp with ThreadedResolver ===")
try:
    import aiohttp
    import asyncio

    async def test_threaded():
        resolver = aiohttp.resolver.ThreadedResolver()
        connector = aiohttp.TCPConnector(resolver=resolver)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                "https://rest.uniprot.org/uniprotkb/search",
                params={"query": "accession:P04637", "format": "json", "size": "1"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                print(f"Status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    print(f"Results count: {len(data.get('results', []))}")

    asyncio.run(test_threaded())
except Exception as e:
    print(f"Exception: {type(e).__name__}: {e}")
