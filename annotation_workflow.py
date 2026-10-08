"""Input snapshots, purpose presets, safe table joins and shared filters."""
import hashlib
import json
from pathlib import Path
import pandas as pd
from uniprot_fetcher import parse_entry, empty_result

BASIC = ["Protein Name", "Gene Name", "Organism", "Protein Function", "Molecular Weight (Da)", "Sequence Length", "Subcellular Localization"]
PRESETS = {
    "Basic / 基本情報": BASIC,
    "Membrane / 膜・分泌": BASIC + ["Receptor", "Secreted Protein", "Signal Peptide", "Transmembrane Regions", "Topological Domains", "Membrane Location", "Extracellular Regions", "Cell Surface Candidate", "Glycosylation Sites", "GO Cellular Component", "Protein Domains", "Protein Families"],
    "Enzymes / 酵素": BASIC + ["Enzyme", "Kinase Activity", "Protease", "Active Sites", "Metal-Binding Sites", "GO Molecular Function", "GO Biological Process", "Protein Domains", "Protein Families"],
    "PTM / 翻訳後修飾": BASIC + ["Phosphorylation Sites", "Glycosylation Sites", "Glycoprotein Annotation", "Disulfide Bonds", "Lipidation Sites", "PTM Details"],
    "Full annotation / 全項目": None,
}
DEMO_PATH = Path(__file__).parent / "test_data"


def normalize_id(value):
    return "" if value is None or pd.isna(value) else str(value).strip()


def input_stats(values):
    cleaned = [normalize_id(value) for value in values]
    valid = [value for value in cleaned if value]
    return {"rows": len(cleaned), "empty": len(cleaned) - len(valid), "unique": len(set(valid)),
            "duplicates": len(valid) - len(set(valid))}


def input_signature(frame, id_column, species, id_type, attrs, mode):
    data = frame.to_json(orient="split", force_ascii=False, default_handler=str) if frame is not None else ""
    return hashlib.sha256(json.dumps([data, id_column, species, id_type, attrs, mode], ensure_ascii=False).encode()).hexdigest()


def public_frame(results):
    if isinstance(results, pd.DataFrame):
        return results[[c for c in results.columns if not c.startswith("_")]].copy()
    return pd.DataFrame([{k: v for k, v in row.items() if not k.startswith("_")} for row in results])


def merge_annotations(original, id_column, results):
    """Keep every original cell and row. Deduplicated results are a lookup."""
    table = public_frame(results)
    if table.empty:
        return original.copy()
    for pid, group in table.groupby("Query ID", dropna=False):
        if len(group) > 1 and any(group[c].nunique(dropna=False) > 1 for c in table.columns):
            raise ValueError(f"Conflicting annotations for {pid}; resolve mapping before export")
    lookup = table.drop_duplicates("Query ID").set_index("Query ID")
    keys = original[id_column].map(normalize_id)
    aligned = lookup.reindex(keys).reset_index(drop=True)
    output = original.copy()
    for column in aligned.columns:
        name = column
        n = 1
        while name in output.columns:
            name = f"{column}_PAIA" + (str(n) if n > 1 else "")
            n += 1
        values = aligned[column].copy()
        if column == "Mapping Status":
            values.loc[keys.to_numpy() == ""] = "Empty input"
        output[name] = values.to_numpy()
    return output


def split_values(value):
    if value is None or pd.isna(value):
        return set()
    return {s.strip() for s in str(value).split(";") if s.strip()}


def filter_results(frame, locations=None, location_mode="ANY", classes=None, class_mode="ALL",
                   ranges=None, text="", terms=None, term_mode="ANY", statuses=None):
    """Groups combine with AND; members of a selected group use ANY or ALL."""
    mask = pd.Series(True, index=frame.index)
    if locations:
        wanted = set(locations)
        sets = frame["Subcellular Localization"].map(split_values)
        mask &= sets.map(lambda have: wanted <= have if location_mode == "ALL" else bool(wanted & have))
    if classes:
        matches = frame[classes].eq(True).fillna(False)
        mask &= matches.all(axis=1) if class_mode == "ALL" else matches.any(axis=1)
    for column, (low, high) in (ranges or {}).items():
        mask &= pd.to_numeric(frame[column], errors="coerce").between(low, high)
    if terms:
        matches = pd.DataFrame({column: frame[column].fillna("").astype(str).str.contains(value, case=False, regex=False)
                                for column, value in terms.items() if value}, index=frame.index)
        if not matches.empty:
            mask &= matches.all(axis=1) if term_mode == "ALL" else matches.any(axis=1)
    if text.strip():
        mask &= frame.fillna("").astype(str).apply(lambda col: col.str.contains(text.strip(), case=False, regex=False)).any(axis=1)
    if statuses:
        mask &= frame["Mapping Status"].isin(statuses)
    return frame.loc[mask].copy()


def demo_input():
    return pd.read_csv(DEMO_PATH / "proteins.csv", dtype={"Protein ID": str}, keep_default_na=False)


def demo_results(ids, attrs, organism_id="9606", id_type="Auto-detect"):
    """Public saved responses only, with explicit fixture provenance."""
    snapshot = json.loads((DEMO_PATH / "uniprot_entries.json").read_text(encoding="utf-8"))
    domains = json.loads((DEMO_PATH / "interpro_entries.json").read_text(encoding="utf-8"))
    entries = snapshot["entries"]
    results = []
    for pid in dict.fromkeys(normalize_id(v) for v in ids if normalize_id(v)):
        if id_type == "UniProt ID":
            entry = entries.get(pid)
        elif id_type in {"Gene Name / Symbol", "Auto-detect"}:
            entry = entries.get(pid) or next((e for e in entries.values() if any(g.get("geneName", {}).get("value") == pid for g in e.get("genes", [])) and (not organism_id or str(e["organism"]["taxonId"]) == organism_id)), None)
        else:
            entry = None
        if not entry:
            result = empty_result(pid, attrs)
        else:
            acc = entry["primaryAccession"]
            use_domains = bool({"Protein Domains", "Protein Families"}.intersection(attrs))
            result = parse_entry(entry, attrs, domains.get(acc) if use_domains else None,
                                 retrieved_at=snapshot["retrieved_at"], release=snapshot.get("release"))
            result.update({"Query ID": pid, "Mapping Status": "Matched", "Candidate Count": 1,
                           "InterPro Status": "Retrieved (saved fixture)" if use_domains else "Not requested",
                           "Species Match": "Not restricted" if not organism_id else "Selected species" if str(entry["organism"]["taxonId"]) == organism_id else "Different species (exact accession)"})
        result["Data Mode"] = "Saved public test data (offline)"
        results.append(result)
    return results
