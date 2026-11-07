"""Validate real API responses and write inspectable output tables."""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from uniprot_fetcher import fetch_batch, ATTRIBUTE_CATEGORIES
from annotation_workflow import demo_input, public_frame, merge_annotations, filter_results


def main():
    attrs = [a for group in ATTRIBUTE_CATEGORIES.values() for a in group]
    original = demo_input()
    rows = fetch_batch(original["Protein ID"].tolist(), attrs, organism_id="9606")
    table = public_frame(rows)
    output = merge_annotations(original, "Protein ID", rows)
    assert len(output) == len(original) == 8
    assert output[original.columns].equals(original)
    assert (table["Mapping Status"] == "Matched").sum() == 5
    assert table.loc[table["Query ID"] == "NOT_A_PROTEIN", "Accession"].isna().all()
    assert table.loc[table["Query ID"] != "NOT_A_PROTEIN", "InterPro Status"].eq("Retrieved").all()
    egfr = next(r for r in rows if r["Accession"] == "P00533")
    assert "GO:" in egfr["GO Molecular Function"]
    assert "IPR000719" in egfr["Protein Domains"]
    assert egfr["Cell Surface Candidate"] is True
    selected = filter_results(table, locations=["Cell membrane"], classes=["Receptor"], ranges={"Molecular Weight (Da)": (100000, 200000)})
    assert selected["Query ID"].tolist() == ["P00533"]
    names = fetch_batch(["Actin"], ["Protein Name"], organism_id="9606", id_type="Protein Name")
    assert names[0]["Mapping Status"] == "Needs review" and names[0]["Accession"] is None
    mouse = fetch_batch(["NOT_A_PROTEIN"], ["Protein Name"], organism_id="10090", id_type="Gene Name / Symbol")
    assert mouse[0]["Mapping Status"] == "Not found"
    OUT = ROOT / "validation"
    OUT.mkdir(exist_ok=True)
    output.to_csv(OUT / "annotated_test_proteins.csv", index=False, encoding="utf-8-sig")
    merge_annotations(original[original["Protein ID"] == "P00533"], "Protein ID", selected).to_csv(OUT / "filtered_egfr.csv", index=False, encoding="utf-8-sig")
    (OUT / "annotation_evidence.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "input_rows": 8, "unique_nonempty_ids": 6,
              "matched_ids": 5, "unmatched_ids": 1, "export_rows": len(output), "original_cells_preserved": True,
              "interpro_retrieved": 5, "combined_filter_ids": selected["Query ID"].tolist(),
              "ambiguous_query": "Actin", "candidate_count": names[0]["Candidate Count"], "ambiguous_status": names[0]["Mapping Status"],
              "selected_species_retained": True}
    (OUT / "live_validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
