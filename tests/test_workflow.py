import pandas as pd
import pytest
from annotation_workflow import demo_input, demo_results, merge_annotations, input_stats, public_frame, filter_results, input_signature
from uniprot_fetcher import ATTRIBUTE_CATEGORIES

ALL = [a for attrs in ATTRIBUTE_CATEGORIES.values() for a in attrs]


def test_export_preserves_original_cells_rows_duplicates_and_empty_ids():
    original = demo_input()
    rows = demo_results(original["Protein ID"].tolist(), ALL)
    output = merge_annotations(original, "Protein ID", rows)
    pd.testing.assert_frame_equal(output[original.columns], original)
    assert len(output) == 8
    assert output["Accession"].tolist()[:6] == ["P00533", "P04637", "P02768", "P00441", "P12830", "P00533"]
    assert output.iloc[6]["Mapping Status"] == "Empty input"
    assert output.iloc[7]["Mapping Status"] == "Not found"
    table = public_frame(rows)
    assert len(table) == 6
    assert (table["Mapping Status"] == "Matched").sum() == 5


def test_colliding_columns_are_retained_and_annotations_are_suffixed():
    original = pd.DataFrame({"Gene Name": ["TP53", " TP53 ", None], "Accession": ["original1", "original2", "original3"], "Protein Name": ["A", "B", "C"]})
    output = merge_annotations(original, "Gene Name", demo_results(original["Gene Name"].tolist(), ALL))
    pd.testing.assert_frame_equal(output[original.columns], original)
    assert output["Accession_PAIA"].tolist()[:2] == ["P04637"] * 2
    assert output["Gene Name_PAIA"].tolist()[:2] == ["TP53"] * 2


def test_conflicting_duplicate_annotations_require_review():
    frame = pd.DataFrame({"ID": ["A"]})
    with pytest.raises(ValueError, match="Conflicting"):
        merge_annotations(frame, "ID", [{"Query ID": "A", "Accession": "P00001"}, {"Query ID": "A", "Accession": "P00002"}])


def test_location_classification_and_mass_filter_select_egfr():
    frame = public_frame(demo_results(demo_input()["Protein ID"].tolist(), ALL))
    filtered = filter_results(frame, locations=["Cell membrane"], classes=["Receptor"], ranges={"Molecular Weight (Da)": (100000, 200000)})
    assert filtered["Query ID"].tolist() == ["P00533"]
    filtered = filter_results(frame, classes=["Cell Surface Candidate"], ranges={"Molecular Weight (Da)": (20000, 100000)})
    assert filtered["Query ID"].tolist() == ["P12830"]


def test_any_all_and_missing_numeric_behavior():
    frame = pd.DataFrame({"Query ID": ["A", "B", "C"], "Subcellular Localization": ["Cell membrane; Nucleus", "Nucleus", None], "Receptor": [True, None, None], "Enzyme": [None, True, None], "Sequence Length": [100, 200, None], "Mapping Status": ["Matched", "Matched", "Not found"]})
    assert filter_results(frame, ["Nucleus", "Cell membrane"], "ALL")["Query ID"].tolist() == ["A"]
    assert filter_results(frame, classes=["Receptor", "Enzyme"], class_mode="ANY")["Query ID"].tolist() == ["A", "B"]
    assert filter_results(frame, classes=["Receptor", "Enzyme"], class_mode="ALL").empty
    assert filter_results(frame, ranges={"Sequence Length": (0, 300)})["Query ID"].tolist() == ["A", "B"]
    assert filter_results(frame, ranges={"Sequence Length": (300, 0)}).empty


def test_literal_text_filter_and_input_statistics():
    assert input_stats([" A ", "A", "", None, "B"]) == {"rows": 5, "unique": 2, "empty": 2, "duplicates": 1}
    frame = public_frame(demo_results(["P00533", "P00441"], ALL))
    assert filter_results(frame, terms={"Protein Domains": "IPR000719"})["Query ID"].tolist() == ["P00533"]
    assert filter_results(frame, text=".*").empty


def test_input_signature_changes_with_original_measurements_and_settings():
    frame = demo_input()
    before = input_signature(frame, "Protein ID", "9606", "Auto-detect", ALL, "Upload")
    frame.loc[0, "Intensity"] = 999
    assert before != input_signature(frame, "Protein ID", "9606", "Auto-detect", ALL, "Upload")
