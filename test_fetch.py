"""Quick test to check if fetch_batch works at all."""
from uniprot_fetcher import fetch_batch

results = fetch_batch(
    ["P04637"],
    ["Protein Name", "Gene Name", "Molecular Weight (Da)", "Sequence Length"],
    organism_id="9606",
)

for r in results:
    for k, v in r.items():
        print(f"  {k}: {v}")
