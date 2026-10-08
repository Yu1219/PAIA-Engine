import copy
from annotation_details import membrane_info
from uniprot_fetcher import parse_entry, ATTRIBUTE_CATEGORIES

ALL = [a for attrs in ATTRIBUTE_CATEGORIES.values() for a in attrs]


def test_egfr_go_domains_positions_and_surface(snapshot, interpro):
    result = parse_entry(snapshot["entries"]["P00533"], ALL, interpro["P00533"])
    assert "GO:" in result["GO Molecular Function"]
    assert "GO:" in result["GO Biological Process"]
    assert "GO:" in result["GO Cellular Component"]
    assert "IPR000719 | Protein kinase domain" in result["Protein Domains"]
    domain = next(r for r in result["_annotation_records"] if r.get("Source") == "InterPro" and "IPR000719" in str(r.get("Value")))
    assert 1 <= domain["Start"] < domain["End"] <= result["Sequence Length"]
    assert result["Cell Surface Candidate"] is True
    assert result["Receptor"] is True
    assert "Cell / plasma membrane" in result["Membrane Location"]
    assert "PF" in result["Pfam Entries"]
    assert result["Protein Families"]


def test_ptm_positions_and_evidence_are_preserved(snapshot):
    entry = snapshot["entries"]["P00533"]
    original = copy.deepcopy(entry)
    result = parse_entry(entry, ALL)
    expected = sum(f["type"] == "Glycosylation" for f in entry["features"])
    assert result["Glycosylation Sites"] == expected > 0
    records = [r for r in result["_annotation_records"] if r["Attribute"] == "PTM Details"]
    assert any(r.get("Start") and r.get("Evidence") for r in records)
    assert any(r.get("References") and "PubMed:" in r["References"] for r in records)
    assert any("Canonical sequence" in str(r.get("Sequence")) for r in records)
    assert entry == original


def test_missing_support_is_not_negative_and_keyword_is_not_site_count():
    result = parse_entry({"primaryAccession": "P00001", "keywords": [{"name": "Glycoprotein"}, {"name": "Signal"}, {"name": "Transcription"}]}, ALL)
    assert result["Glycosylation Sites"] == 0
    assert result["Glycoprotein Annotation"] is True
    assert result["Secreted Protein"] is None
    assert result["Transcription Factor"] is None
    assert result["Receptor"] is None
    assert result["Cell Surface Candidate"] is None
    assert result["GO Molecular Function"] is None


def test_metal_features_count_once_and_zinc_keyword_does_not_invent_site():
    entry = {"primaryAccession": "P00001", "keywords": [{"name": "Zinc"}],
             "features": [{"type": "Metal binding", "description": "Zinc", "location": {}}]}
    result = parse_entry(entry, ["Metal-Binding Sites", "Zinc-Binding Sites"])
    assert result["Metal-Binding Sites"] == 1
    assert result["Zinc-Binding Sites"] == 0


def test_intracellular_membrane_and_lumen_do_not_imply_cell_surface():
    entry = {"comments": [{"commentType": "SUBCELLULAR LOCATION", "subcellularLocations": [{"location": {"value": "Endoplasmic reticulum membrane"}}]}],
             "features": [{"type": "Topological domain", "description": "Lumenal"}]}
    label, _, candidate = membrane_info(entry)
    assert label == "Intracellular membrane"
    assert candidate is None


def test_surface_evidence_cannot_mix_isoforms():
    entry = {"comments": [{"commentType": "SUBCELLULAR LOCATION", "molecule": "Isoform 2", "subcellularLocations": [{"location": {"value": "Cell membrane"}}]}],
             "features": [{"type": "Topological domain", "description": "Extracellular", "location": {}}]}
    assert membrane_info(entry)[2] is None
    entry["comments"][0].pop("molecule")
    entry["features"][0]["location"]["sequence"] = "P00001-2"
    assert membrane_info(entry)[2] is None


def test_uncertain_ptm_positions_and_isoform_ids_remain_in_records():
    entry = {"primaryAccession": "P00001", "features": [{"type": "Lipidation", "description": "S-palmitoyl cysteine",
             "location": {"sequence": "P00001-2", "start": {"value": 8, "modifier": "UNSURE"}, "end": {"value": 8, "modifier": "UNSURE"}},
             "evidences": [{"evidenceCode": "ECO:0000269", "source": "PubMed", "id": "123"}]}]}
    result = parse_entry(entry, ["PTM Details", "Lipidation Sites"])
    assert "8?" in result["PTM Details"] and "P00001-2" in result["PTM Details"]
    feature = next(r for r in result["_annotation_records"] if r["Attribute"] == "PTM Details")
    assert feature["References"] == "PubMed:123"
    assert result["Lipidation Sites"] == 1


def test_ph_dependence_numbers_are_not_misreported_as_measured_pi(snapshot):
    entry = copy.deepcopy(snapshot["entries"]["P00441"])
    entry["comments"].append({"commentType": "BIOPHYSICOCHEMICAL PROPERTIES", "phDependence": {"texts": [{"value": "Activity at pH 99.0; pI not established"}]}})
    result = parse_entry(entry, ["Isoelectric Point (pI)"])
    assert 0 < result["Isoelectric Point (pI)"] < 14
    rec = next(r for r in result["_annotation_records"] if r["Attribute"] == "Isoelectric Point (pI)")
    assert rec["Source"] == "Local sequence calculation"
