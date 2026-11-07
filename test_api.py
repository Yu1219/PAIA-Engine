"""Diagnose the UniProt API connection."""
import aiohttp
import asyncio

async def test():
    url = "https://rest.uniprot.org/uniprotkb/search"
    params = {"query": "accession:P04637", "format": "json", "size": "1"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                print(f"Status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("results", [])
                    print(f"Results count: {len(results)}")
                    if results:
                        entry = results[0]
                        print(f"primaryAccession: {entry.get('primaryAccession')}")
                        print(f"organism: {entry.get('organism', {}).get('scientificName')}")
                        seq = entry.get("sequence", {})
                        print(f"molWeight: {seq.get('molWeight')}")
                        print(f"length: {seq.get('length')}")
                else:
                    text = await resp.text()
                    print(f"Error response: {text[:500]}")
    except Exception as e:
        print(f"Exception: {type(e).__name__}: {e}")

asyncio.run(test())
