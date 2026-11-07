"""Download public, reproducible annotation fixtures; never uploads user files."""
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test_data"
IDS = ["P00533", "P04637", "P02768", "P00441", "P12830"]


def download(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response), dict(response.headers)


def main():
    OUT.mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=5) as pool:
        entries = list(pool.map(lambda pid: download(f"https://rest.uniprot.org/uniprotkb/{pid}.json"), IDS))
    snapshot = {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "release": entries[0][1].get("X-UniProt-Release"),
        "entries": {pid: data for pid, (data, headers) in zip(IDS, entries)},
    }
    (OUT / "uniprot_entries.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    domains = {}
    for pid in IDS:
        data, headers = download(f"https://www.ebi.ac.uk/interpro/api/entry/interpro/protein/uniprot/{pid}/?page_size=200")
        domains[pid] = data
    (OUT / "interpro_entries.json").write_text(json.dumps(domains, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Saved public UniProt and InterPro snapshots:", ", ".join(IDS))
    print("InterPro example:", json.dumps(domains[IDS[0]]["results"][0])[:1700])


if __name__ == "__main__":
    main()
