from pathlib import Path
import copy
import pytest
from streamlit.testing.v1 import AppTest
from annotation_workflow import demo_input, demo_results, PRESETS
from uniprot_fetcher import ATTRIBUTE_CATEGORIES, search_result

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def demo_app():
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.radio(key="input_mode").set_value("🧪 Test dataset (offline)").run()
    app.selectbox(key="annotation_preset").set_value("Full annotation / 全項目").run()
    app.button[0].click().run()
    assert not app.exception
    return app


@pytest.mark.parametrize("preset", list(PRESETS))
def test_presets_apply_expected_attributes(preset):
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.selectbox(key="annotation_preset").set_value(preset).run()
    actual = [attr for category in ATTRIBUTE_CATEGORIES for attr in app.multiselect(key=f"ms_{category}").value]
    expected = PRESETS[preset]
    if expected is None:
        assert len(actual) == sum(map(len, ATTRIBUTE_CATEGORIES.values()))
    else:
        assert set(actual) == set(expected)
    assert not app.exception


def test_demo_flow_details_and_all_existing_explorers():
    app = demo_app()
    rows = app.session_state["result_rows"]
    assert len(rows) == 6 and sum(r["Mapping Status"] == "Matched" for r in rows) == 5
    assert len(app.session_state["run_snapshot"]["input_frame"]) == 8
    assert len(app.get("download_button")) >= 3
    for section in app.radio(key="active_section").options:
        app.radio(key="active_section").set_value(section).run()
        assert not app.exception, section
    app.radio(key="active_section").set_value("📋 Annotation Table").run()
    app.selectbox(key="detail_protein").set_value("P04637").run()
    assert any("TP53" in s.value for s in app.subheader)
    app.selectbox(key="detail_attribute_P04637").set_value("PTM Details").run()
    assert not app.exception


def test_combined_filter_and_empty_result_do_not_crash():
    app = demo_app()
    app.multiselect(key="combined_locations").set_value(["Cell membrane"]).run()
    app.multiselect(key="combined_classes").set_value(["Receptor"]).run()
    # The displayed compact result table now contains only EGFR.
    tables = [frame.value for frame in app.dataframe if "Query ID" in frame.value.columns and "Cell Surface Candidate" in frame.value.columns]
    assert any(frame["Query ID"].tolist() == ["P00533"] for frame in tables)
    app.multiselect(key="combined_numeric").set_value(["Molecular Weight (Da)"]).run()
    app.number_input(key="upper_Molecular Weight (Da)").set_value(10000).run()
    assert not app.exception
    assert any("No proteins match" in message.value for message in app.info)
    for section in app.radio(key="active_section").options:
        app.radio(key="active_section").set_value(section).run()
        assert not app.exception


def test_input_change_warns_and_keeps_original_run_snapshot():
    app = demo_app()
    saved = app.session_state["run_snapshot"]["input_frame"].copy()
    app.radio(key="input_mode").set_value("⌨️ Type Protein IDs").run()
    app.text_area[0].set_value("P00441").run()
    assert any("Input or settings changed" in w.value for w in app.warning)
    assert app.session_state["run_snapshot"]["input_frame"].equals(saved)
    assert not app.exception


def test_ambiguous_candidate_can_be_explicitly_confirmed(snapshot, monkeypatch):
    app = demo_app()
    attrs = app.session_state["selected_attrs_snapshot"]
    ambiguous = search_result({"results": [snapshot["entries"]["P00533"], snapshot["entries"]["P04637"]]}, "generic name", attrs)
    app.session_state["result_rows"] = [ambiguous] + app.session_state["result_rows"]
    from annotation_workflow import public_frame
    app.session_state["result_df"] = public_frame(app.session_state["result_rows"])
    app.run()
    selector = next(s for s in app.selectbox if s.label == "Resolve generic name")
    selector.select_index(1).run()
    def fake_fetch(ids, attrs, **kwargs):
        assert ids == ["P00533"] and kwargs["id_type"] == "UniProt ID"
        return demo_results(ids, attrs)
    monkeypatch.setattr("gui_helpers.fetch_batch", fake_fetch)
    next(b for b in app.button if b.key == "confirm_mappings").click().run()
    assert not app.exception
    chosen = app.session_state["result_rows"][0]
    assert chosen["Query ID"] == "generic name"
    assert chosen["Accession"] == "P00533"
    assert chosen["Mapping Status"] == "Matched"
    assert chosen["Mapping Method"] == "User-confirmed candidate"
