"""Streamlit input review, shared filters and per-protein detail panels."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from annotation_workflow import public_frame, input_stats, filter_results, split_values
from annotation_details import BOOLEAN_ATTRIBUTES
from uniprot_fetcher import NUMERIC_ATTRIBUTES, fetch_batch


def input_preview(frame, column):
    if frame is None or not column:
        return
    stats = input_stats(frame[column].tolist())
    with st.expander("Input preview / 入力確認", expanded=True):
        cols = st.columns(4)
        for col, (label, value) in zip(cols, [("Input rows", stats["rows"]), ("Unique IDs", stats["unique"]), ("Empty IDs", stats["empty"]), ("Repeated IDs", stats["duplicates"])]):
            col.metric(label, value)
        st.dataframe(frame.head(10), width="stretch", hide_index=True)
        st.caption("Repeated IDs are fetched once. Every original row, empty ID and measured value is retained in the full export.")


def mapping_review(rows, attrs, snapshot):
    with st.expander("Identifier mapping / ID対応付けの確認", expanded=any(r.get("Mapping Status") != "Matched" for r in rows)):
        frame = public_frame(rows)
        cols = [c for c in ["Query ID", "Accession", "Gene Name", "Protein Name", "Organism", "Taxonomy ID", "Reviewed", "Mapping Status", "Candidate Count", "Species Match"] if c in frame]
        st.dataframe(frame[cols], width="stretch", hide_index=True)
        if frame.get("Species Match", pd.Series(dtype=str)).str.contains("Different species", na=False).any():
            st.warning("Exact accessions from a different species are shown explicitly. Gene/name searches stay within the selected species.")
        choices = {}
        for index, row in enumerate(rows):
            if row.get("Mapping Status") != "Needs review":
                continue
            candidates = row.get("_candidates", [])
            labels = ["Keep unresolved / 未確定のまま"]
            for entry in candidates:
                name = entry.get("proteinDescription", {}).get("recommendedName", {}).get("fullName", {}).get("value", "")
                labels.append(f"{entry['primaryAccession']} | {name} | {entry.get('organism', {}).get('scientificName', '')}")
            st.caption(f"{row['Query ID']}: {row['Candidate Count']} candidates; showing {len(candidates)}. Refine the input if the desired match is absent.")
            choice = st.selectbox(f"Resolve {row['Query ID']}", labels, key=f"resolve_{snapshot['signature']}_{index}")
            if choice != labels[0]:
                choices[index] = candidates[labels.index(choice) - 1]["primaryAccession"]
        if choices and st.button("Apply confirmed mappings / 選択した対応を確定", key="confirm_mappings"):
            with st.spinner("Fetching confirmed candidates…"):
                matched = fetch_batch(list(dict.fromkeys(choices.values())), attrs, organism_id=snapshot["organism_id"], id_type="UniProt ID")
            lookup = {r["Query ID"]: r for r in matched}
            updated = list(rows)
            for index, acc in choices.items():
                chosen = lookup[acc]
                if chosen["Mapping Status"] != "Matched":
                    st.warning(f"Could not retrieve {acc}. The original mapping remains unresolved.")
                    continue
                chosen = dict(chosen, **{"Query ID": rows[index]["Query ID"], "Candidate Count": rows[index]["Candidate Count"], "Mapping Method": "User-confirmed candidate"})
                updated[index] = chosen
            st.session_state.result_rows = updated
            st.session_state.result_df = public_frame(updated)
            st.rerun()


def shared_filters(frame):
    with st.expander("Combined filters / 条件を組み合わせて絞り込み", expanded=True):
        st.caption("Location, classification, numeric and text groups combine with AND. Missing support is excluded when an affirmative condition is selected.")
        a, b = st.columns(2)
        with a:
            locations = sorted(set().union(*(split_values(v) for v in frame.get("Subcellular Localization", []))))
            locs = st.multiselect("Subcellular locations", locations, key="combined_locations")
            loc_mode = st.radio("Location matching", ["ANY", "ALL"], horizontal=True, key="combined_location_mode")
        with b:
            boolean_cols = sorted(c for c in BOOLEAN_ATTRIBUTES if c in frame)
            classes = st.multiselect("Positive classifications", boolean_cols, key="combined_classes")
            class_mode = st.radio("Classification matching", ["ALL", "ANY"], horizontal=True, key="combined_class_mode")
        numeric_cols = sorted(c for c in NUMERIC_ATTRIBUTES if c in frame and pd.to_numeric(frame[c], errors="coerce").notna().any())
        selected_numeric = st.multiselect("Numeric conditions", numeric_cols, key="combined_numeric")
        ranges = {}
        for column in selected_numeric:
            series = pd.to_numeric(frame[column], errors="coerce").dropna()
            low, high = float(series.min()), float(series.max())
            c1, c2 = st.columns(2)
            lower = c1.number_input(f"{column}: minimum", value=low, key=f"lower_{column}")
            upper = c2.number_input(f"{column}: maximum", value=high, key=f"upper_{column}")
            if lower > upper:
                st.warning(f"{column}: minimum exceeds maximum; no proteins will match.")
            ranges[column] = (lower, upper)
        text = st.text_input("Search names, IDs or annotations", key="combined_text")
        term_columns = [c for c in frame if c.startswith("GO ") or c in {"Protein Domains", "Protein Families", "Membrane Location", "PTM Details"}]
        terms = {}
        if term_columns:
            chosen_terms = st.multiselect("Annotation-specific text conditions", term_columns, key="combined_terms")
            for column in chosen_terms:
                terms[column] = st.text_input(f"Contains in {column}", key=f"term_{column}")
        statuses = st.multiselect("Mapping status", sorted(frame["Mapping Status"].unique()), key="combined_statuses")
        filtered = filter_results(frame, locs, loc_mode, classes, class_mode, ranges, text, terms, statuses=statuses)
        st.caption(f"{len(filtered)} / {len(frame)} unique input IDs match. Full export retains the original input rows.")
        return filtered


def display_frame(frame):
    output = frame.copy()
    for column in BOOLEAN_ATTRIBUTES.intersection(output.columns):
        output[column] = output[column].map(lambda v: "Supported" if v is True or v == True else "No supporting annotation")
    return output


def protein_details(row):
    if row is None:
        st.info("Select a row to inspect its annotations and supporting evidence.")
        return
    st.subheader(row.get("Gene Name") or row["Query ID"])
    st.write(row.get("Protein Name") or "No matched protein")
    st.caption(f"Mapping: {row['Mapping Status']} • Species: {row.get('Organism') or 'unresolved'}")
    if row.get("Mapping Status") != "Matched":
        st.info("Resolve this identifier before interpreting its annotations.")
        return
    st.link_button("Open UniProt", row["UniProt URL"])
    st.caption(f"Retrieved: {row.get('Retrieved At')} • UniProt release: {row.get('UniProt Release') or 'not provided'} • Entry version: {row.get('Entry Version')}")
    st.caption("Reviewed means database curation; it does not establish experimental evidence for every annotation.")
    if row.get("Data Mode"):
        st.info(row["Data Mode"])
    if row.get("InterPro Status", "").startswith("Fetch error"):
        st.warning("InterPro retrieval failed. UniProt domains remain available; missing InterPro data is not a negative result.")
    st.write(row.get("Protein Function") or "No functional description registered.")
    records = pd.DataFrame(row.get("_annotation_records", []))
    if records.empty:
        return
    choices = ["All selected annotations"] + sorted(records["Attribute"].dropna().unique())
    choice = st.selectbox("Inspect annotation", choices, key=f"detail_attribute_{row['Query ID']}")
    if choice != choices[0]:
        records = records[records["Attribute"] == choice]
    records = records.copy()
    records["Value"] = records["Value"].map(lambda value: None if value is None else str(value))
    st.dataframe(records, width="stretch", hide_index=True, column_config={"URL": st.column_config.LinkColumn("Source link")})
    if "Start" in records and "End" in records:
        positions = records.copy()
        positions["Start"] = pd.to_numeric(positions["Start"], errors="coerce")
        positions["End"] = pd.to_numeric(positions["End"], errors="coerce")
        positions = positions.dropna(subset=["Start", "End"])
        # Isoform positions are shown in the evidence table, never overlaid on the canonical sequence.
        positions = positions[positions["Sequence"] == "Canonical sequence"] if "Sequence" in positions else positions
        if not positions.empty:
            fig = go.Figure()
            for _, feature in positions.iterrows():
                fig.add_trace(go.Scatter(x=[feature["Start"], feature["End"]], y=[feature["Attribute"]] * 2,
                                         mode="lines+markers", line=dict(width=6), name=str(feature["Value"]),
                                         text=[str(feature["Value"])] * 2, hovertemplate="%{text}<br>Position %{x}<extra></extra>"))
            length = row.get("_entry", {}).get("sequence", {}).get("length", positions["End"].max())
            fig.update_layout(showlegend=False, height=280, margin=dict(l=10, r=10, t=10, b=30), xaxis_title="Residue position (1-based, inclusive)", xaxis_range=[1, length], template="plotly_dark")
            st.plotly_chart(fig, width="stretch")
    st.caption("PTM counts are registered features. Zero means no registered site. Surface candidates require supporting location/topology; accessibility remains unverified.")
    st.caption("Biological classifications are entry-level rules. Check the sequence/isoform context of the supporting records.")
    st.download_button("Download evidence JSON", json_bytes(row), file_name=f"{row['Accession']}_evidence.json", mime="application/json")


def json_bytes(row):
    import json
    return json.dumps(row, ensure_ascii=False, indent=2, default=str).encode("utf-8")
