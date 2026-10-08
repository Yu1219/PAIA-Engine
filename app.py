"""
PAIA Engine — Protein-Attribute Insights & Annotation
Main Streamlit application.
"""

import streamlit as st
import pandas as pd
import io
import pathlib

from uniprot_fetcher import (
    ATTRIBUTE_CATEGORIES,
    ATTRIBUTE_SOURCES,
    NUMERIC_ATTRIBUTES,
    CATEGORICAL_ATTRIBUTES,
    ID_TYPES,
    fetch_batch,
)
from visualizations import plot_pie, plot_histogram, summary_stats
from annotation_workflow import PRESETS, demo_input, demo_results, input_stats, input_signature, public_frame, merge_annotations
from gui_helpers import input_preview, mapping_review, shared_filters, display_frame, protein_details

for state_key, initial in {"result_df": None, "result_rows": [], "selected_attrs_snapshot": [], "run_snapshot": None}.items():
    if state_key not in st.session_state:
        st.session_state[state_key] = initial


def apply_preset():
    selected = PRESETS[st.session_state.annotation_preset]
    for category, attrs in ATTRIBUTE_CATEGORIES.items():
        st.session_state[f"ms_{category}"] = attrs.copy() if selected is None else [a for a in attrs if a in selected]


# ─── Page config ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="PAIA Engine",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Inject custom CSS ───────────────────────────────────────────────
CSS_PATH = pathlib.Path(__file__).parent / "style.css"
if CSS_PATH.exists():
    st.markdown(f"<style>{CSS_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


# ─── Header ──────────────────────────────────────────────────────────
st.markdown("""
<div class="paia-header">
    <h1>🧬 PAIA Engine</h1>
    <p>Protein-Attribute Insights &amp; Annotation — High-speed batch retrieval of biological and physicochemical features from UniProt</p>
</div>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════
#  SIDEBAR — Data Input & Attribute Selection
# ═══════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("### 📂 Data Input")

    # ── Species selector ────────────────────────────────────────────
    st.markdown("### 🌍 Species")
    SPECIES_MAP = {
        "Homo sapiens (Human)": "9606",
        "Mus musculus (Mouse)": "10090",
        "Rattus norvegicus (Rat)": "10116",
        "Danio rerio (Zebrafish)": "7955",
        "Drosophila melanogaster (Fruit fly)": "7227",
        "Caenorhabditis elegans (Worm)": "6239",
        "Saccharomyces cerevisiae (Yeast)": "4932",
        "Any organism": None,
    }
    species_choice = st.selectbox(
        "Restrict gene-name searches to",
        options=list(SPECIES_MAP.keys()),
        index=0,
        help="When searching by gene name (e.g. ACTB), results are "
             "filtered to this organism. UniProt accession IDs (e.g. "
             "P60709) always return the exact protein regardless.",
    )
    organism_id = SPECIES_MAP[species_choice]

    st.markdown("---")

    input_mode = st.radio(
        "Choose input method",
        ["📄 Upload CSV / TSV", "⌨️ Type Protein IDs", "🧪 Test dataset (offline)"],
        horizontal=True,
        key="input_mode",
        label_visibility="collapsed",
    )

    protein_ids: list[str] = []
    uploaded_df: pd.DataFrame | None = None
    input_frame = None
    id_col = None

    if input_mode == "📄 Upload CSV / TSV":
        uploaded_file = st.file_uploader(
            "Upload a file with a Protein ID column",
            type=["csv", "tsv", "txt", "xlsx", "xls"],
        )
        if uploaded_file is not None:
            try:
                fname = uploaded_file.name.lower()
                if fname.endswith((".xlsx", ".xls")):
                    uploaded_df = pd.read_excel(uploaded_file, keep_default_na=False)
                else:
                    raw = uploaded_file.getvalue().decode("utf-8-sig")
                    sep = "\t" if ("\t" in raw[:2000]) else ","
                    uploaded_df = pd.read_csv(io.StringIO(raw), sep=sep, dtype=str, keep_default_na=False)

                # Let user pick the ID column
                id_col = st.selectbox(
                    "Select the identifier column",
                    uploaded_df.columns.tolist(),
                )
                protein_ids = (
                    uploaded_df[id_col]
                    .dropna()
                    .astype(str)
                    .str.strip()
                    .tolist()
                )
                st.success(f"✅ Loaded **{len(protein_ids)}** protein IDs")
            except Exception as e:
                st.error(f"Error reading file: {e}")
    elif input_mode == "⌨️ Type Protein IDs":
        typed_text = st.text_area(
            "Enter Protein IDs (one per line, or comma-separated)",
            height=160,
            placeholder="P04637\nACTB\nGAPDH\nP00533\nTP53",
            help="You can enter UniProt accession IDs (e.g. P04637) "
                 "or gene symbols (e.g. ACTB, GAPDH, TP53).",
        )
        if typed_text.strip():
            # Support both newline and comma separation
            raw_ids = typed_text.replace(",", "\n").split("\n")
            protein_ids = [pid.strip() for pid in raw_ids if pid.strip()]
            st.info(f"📋 {len(protein_ids)} protein IDs entered")
            input_frame = pd.DataFrame({"Protein ID": raw_ids})
            id_col = "Protein ID"
    else:
        input_frame = demo_input()
        id_col = "Protein ID"
        protein_ids = [str(v).strip() for v in input_frame[id_col] if str(v).strip()]
        st.info("Saved public UniProt / InterPro data: 5 proteins, duplicate and empty IDs, plus an unmatched ID. No network required.")
    if uploaded_df is not None:
        input_frame = uploaded_df


    # ── Identifier type selector (shared by both modes) ──────────
    st.markdown("### 🏷️ Identifier Type")
    id_type = st.selectbox(
        "What type of identifier are you using?",
        options=ID_TYPES,
        index=0,
        help=(
            "**Auto-detect** — Automatically identifies UniProt accessions vs. "
            "gene symbols (default).\n\n"
            "**UniProt ID** — e.g. P04637, Q9Y6K9\n\n"
            "**Gene Name / Symbol** — e.g. TP53, ACTB, GAPDH\n\n"
            "**Protein Name** — e.g. Tumor protein p53\n\n"
            "**Ensembl ID** — e.g. ENSG00000141510\n\n"
            "**RefSeq ID** — e.g. NP_000537.3"
        ),
    )

    st.markdown("---")
    st.markdown("### 🎯 Attribute Selection")

    preset = st.selectbox("Purpose preset / 用途別プリセット", list(PRESETS), key="annotation_preset", on_change=apply_preset)
    if not any(f"ms_{category}" in st.session_state for category in ATTRIBUTE_CATEGORIES):
        apply_preset()
    st.caption("Choose a preset, then adjust individual attributes below.")
    selected_attrs: list[str] = []
    for category, attrs in ATTRIBUTE_CATEGORIES.items():
        with st.expander(category, expanded=False):
            chosen = st.multiselect(
                f"Select from {category}",
                options=attrs,
                label_visibility="collapsed",
                key=f"ms_{category}",
            )
            selected_attrs.extend(chosen)
            # Show source info for selected attributes (hidden until clicked)
            if chosen:
                with st.expander("ℹ️ Data sources", expanded=False):
                    for attr in chosen:
                        src = ATTRIBUTE_SOURCES.get(attr, "")
                        if src:
                            st.caption(f"**{attr}:** {src}")

    st.markdown("---")

    if input_frame is not None:
        stats = input_stats(input_frame[id_col].tolist())
        st.caption(f"{stats['unique']} unique IDs • {stats['duplicates']} repeats • {stats['empty']} empty")
    st.caption(f"{len(selected_attrs)} attributes selected")
    can_run = len(protein_ids) > 0 and len(selected_attrs) > 0
    run_btn = st.button(
        "🚀  Annotate Proteins",
        width='stretch',
        disabled=not can_run,
        type="primary",
    )

    if not can_run:
        if len(protein_ids) == 0:
            st.caption("⚠️ Provide at least one protein ID to begin.")
        if len(selected_attrs) == 0:
            st.caption("⚠️ Select at least one attribute to retrieve.")


# ═══════════════════════════════════════════════════════════════════════
#  MAIN AREA — Results
# ═══════════════════════════════════════════════════════════════════════

input_preview(input_frame, id_col)
current_signature = input_signature(input_frame, id_col, organism_id, id_type, selected_attrs, input_mode)

if run_btn:
    unique_ids = list(dict.fromkeys(pid.strip() for pid in protein_ids if pid.strip()))
    progress_bar = st.progress(0, text="Initialising annotation engine…")
    completed = {"n": 0}
    def _progress():
        completed["n"] += 1
        progress_bar.progress(min(completed["n"] / len(unique_ids), 1.0), text=f"Fetching {completed['n']}/{len(unique_ids)} unique IDs")
    if input_mode == "🧪 Test dataset (offline)":
        results = demo_results(unique_ids, selected_attrs, organism_id, id_type)
    else:
        results = fetch_batch(unique_ids, selected_attrs, progress_callback=_progress,
                              organism_id=organism_id, id_type=id_type)
    progress_bar.progress(1.0, text="Annotation finished; review identifier mappings below.")
    result_df = public_frame(results)
    front = [c for c in ["Query ID", "Accession", "Mapping Status", "Gene Name", "Protein Name", "Organism"] if c in result_df]
    result_df = result_df[front + [c for c in result_df if c not in front]]
    st.session_state.result_rows = results
    st.session_state.result_df = result_df
    st.session_state.selected_attrs_snapshot = selected_attrs.copy()
    st.session_state.run_snapshot = {"input_frame": input_frame.copy(deep=True), "id_col": id_col,
                                     "organism_id": organism_id, "id_type": id_type, "mode": input_mode,
                                     "signature": current_signature}
    # Filters belong to the completed run. Clear stale widget values before rendering.
    for key in list(st.session_state):
        if key.startswith(("combined_", "lower_", "upper_", "term_", "detail_")) or key in {"active_section", "table_columns", "loc_filter", "bio_filter", "pie_selector", "hist_selector"}:
            del st.session_state[key]

# ─── Display results ─────────────────────────────────────────────────
result_df = st.session_state.result_df
sel_attrs = st.session_state.selected_attrs_snapshot

if result_df is not None and not result_df.empty:

    # ── Summary badges ────────────────────────────────────────────────
    n_proteins = len(result_df)
    n_attrs = len(sel_attrs)
    n_success = int((result_df["Mapping Status"] == "Matched").sum())
    snapshot = st.session_state.run_snapshot
    if snapshot and snapshot["signature"] != current_signature:
        st.warning("Input or settings changed after this run. These results and exports belong to the saved input; run annotation again to update them.")
    st.caption("Blank classification = no supporting annotation. Site counts refer to registered features, not proven biological absence.")
    mapping_review(st.session_state.result_rows, sel_attrs, snapshot)
    full_result_df = result_df
    result_df = shared_filters(full_result_df)
    if result_df.empty:
        st.info("No proteins match the current filters. Clear or adjust the filters to inspect results.")

    st.markdown(f"""
    <div class="stat-row">
        <div class="stat-badge">
            <div class="value">{n_proteins}</div>
            <div class="label">Proteins Queried</div>
        </div>
        <div class="stat-badge">
            <div class="value">{n_success}</div>
            <div class="label">Successfully Annotated</div>
        </div>
        <div class="stat-badge">
            <div class="value">{n_attrs}</div>
            <div class="label">Attributes Retrieved</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Section Navigation (persists across reruns via session state) ──
    has_loc = "Subcellular Localization" in result_df.columns

    # Check which biological classification columns are present
    BIO_CLASS_ATTRS = [
        "Receptor", "Secreted Protein", "Cell Adhesion",
        "Transporter / Channel", "Enzyme", "Transcription Factor",
        "Protease", "Cytokine / Growth Factor", "Structural Protein",
        "Immune-Related",
    ]
    bio_cols = [c for c in BIO_CLASS_ATTRS if c in result_df.columns]
    has_bio = len(bio_cols) > 0

    section_labels = [
        "📋 Annotation Table",
        "🥧 Pie Charts",
        "📊 Histograms",
    ]
    if has_loc:
        section_labels.append("🔬 Localization Explorer")
    if has_bio:
        section_labels.append("🧬 Classification Explorer")

    active_section = st.radio(
        "Navigate to",
        section_labels,
        horizontal=True,
        key="active_section",
        label_visibility="collapsed",
    )

    st.markdown("---")

    # ── Annotation Table ──────────────────────────────────────────────
    if active_section == "📋 Annotation Table":
        default_columns = [c for c in ["Query ID", "Accession", "Mapping Status", "Gene Name", "Protein Name", "Organism", "Subcellular Localization", "Membrane Location", "Cell Surface Candidate", "Molecular Weight (Da)"] if c in result_df]
        visible_columns = st.multiselect("Visible table columns", result_df.columns.tolist(), default=default_columns, key="table_columns")
        table_col, detail_col = st.columns([3, 2])
        with table_col:
            table_state = st.dataframe(display_frame(result_df[visible_columns]), width="stretch", hide_index=True,
                                      height=min(38 * len(result_df) + 80, 550), on_select="rerun",
                                      selection_mode="single-row", key="annotation_table")
            st.caption("Click a row for its function, feature positions and supporting records.")
        with detail_col:
            selected = table_state.selection.rows
            selected_id = result_df.iloc[selected[0]]["Query ID"] if selected and selected[0] < len(result_df) else None
            if not result_df.empty:
                options = result_df["Query ID"].tolist()
                selected_id = st.selectbox("Inspect a protein", options, index=options.index(selected_id) if selected_id in options else 0,
                                           key="detail_protein") if selected_id is None else selected_id
            row = next((r for r in st.session_state.result_rows if r["Query ID"] == selected_id), None)
            protein_details(row)

    # ── Pie Charts ────────────────────────────────────────────────────
    elif active_section == "🥧 Pie Charts":
        # Determine which columns can be shown as pie
        pie_candidates = []
        for attr in sel_attrs:
            if attr in result_df.columns:
                if attr in CATEGORICAL_ATTRIBUTES:
                    pie_candidates.append(attr)
                elif attr in NUMERIC_ATTRIBUTES:
                    # Count-type numerics (sites) can be shown as presence/absence pie
                    if "Sites" in attr or "Activity" in attr:
                        pie_candidates.append(attr)
                elif result_df[attr].dtype == object or result_df[attr].dtype == bool:
                    pie_candidates.append(attr)

        if pie_candidates:
            # Let user choose which attributes to visualise
            chosen_pies = st.multiselect(
                "Select attributes for pie chart visualization",
                options=pie_candidates,
                default=pie_candidates,
                key="pie_selector",
            )

            if chosen_pies:
                # Arrange in columns (2 per row)
                for i in range(0, len(chosen_pies), 2):
                    cols = st.columns(2)
                    for j, col in enumerate(cols):
                        idx = i + j
                        if idx < len(chosen_pies):
                            attr = chosen_pies[idx]
                            with col:
                                fig = plot_pie(result_df, attr)
                                st.plotly_chart(fig, width='stretch', key=f"pie_{attr}_{idx}")
            else:
                st.info("Select at least one attribute above to generate pie charts.")
        else:
            st.info("No categorical attributes were selected for annotation. "
                    "Add attributes like *Kinase Activity*, *Subcellular Localization*, "
                    "or *Organism* to see pie charts.")

    # ── Histograms ────────────────────────────────────────────────────
    elif active_section == "📊 Histograms":
        hist_candidates = [
            attr for attr in sel_attrs
            if attr in result_df.columns and attr in NUMERIC_ATTRIBUTES
        ]

        if hist_candidates:
            chosen_hists = st.multiselect(
                "Select numeric attributes for histogram visualization",
                options=hist_candidates,
                default=hist_candidates,
                key="hist_selector",
            )

            if chosen_hists:
                for attr in chosen_hists:
                    st.markdown(f"<div class='card'><h3>{attr}</h3></div>",
                                unsafe_allow_html=True)
                    col_chart, col_stats = st.columns([3, 1])
                    with col_chart:
                        fig = plot_histogram(result_df, attr)
                        st.plotly_chart(fig, width='stretch', key=f"hist_{attr}")
                    with col_stats:
                        stats = summary_stats(result_df, attr)
                        if stats:
                            for k, v in stats.items():
                                st.metric(k, v)
            else:
                st.info("Select at least one numeric attribute above to generate histograms.")
        else:
            st.info("No numeric attributes were selected for annotation. "
                    "Add *Molecular Weight*, *Isoelectric Point*, or *Sequence Length* "
                    "to see histograms.")

    # ── Localization Explorer ─────────────────────────────────────────
    elif has_loc and active_section == "🔬 Localization Explorer":
            loc_col = "Subcellular Localization"
            loc_series = result_df[loc_col].dropna()

            if loc_series.empty:
                st.info("No subcellular localization data available in the results.")
            else:
                # --- Build exploded long-form table ---
                # Each protein can have multiple locations separated by "; "
                id_col_name = "Query ID" if "Query ID" in result_df.columns else "Accession"
                name_col = "Protein Name" if "Protein Name" in result_df.columns else None

                rows = []
                for _, row in result_df.iterrows():
                    raw_loc = row.get(loc_col)
                    if pd.isna(raw_loc) or not raw_loc:
                        continue
                    locs = [l.strip() for l in str(raw_loc).split(";") if l.strip()]
                    pid = row.get(id_col_name, "")
                    pname = row.get(name_col, "") if name_col else ""
                    for loc in locs:
                        rows.append({
                            "Protein": pid,
                            "Protein Name": pname,
                            "Location": loc,
                        })

                loc_df = pd.DataFrame(rows)
                all_locations = sorted(loc_df["Location"].unique())

                st.markdown("""
                <div class="card">
                    <h3>Subcellular Localization Explorer</h3>
                    <p style="color: var(--text-muted); font-size:0.88rem; margin:0;">
                        Proteins often reside in multiple compartments. Select one or more 
                        locations below to find all proteins associated with that compartment.
                    </p>
                </div>
                """, unsafe_allow_html=True)

                # --- Summary badges ---
                n_unique_locs = len(all_locations)
                n_proteins_with = loc_series.shape[0]
                avg_locs = round(loc_df.groupby("Protein")["Location"].count().mean(), 1)

                st.markdown(f"""
                <div class="stat-row">
                    <div class="stat-badge">
                        <div class="value">{n_unique_locs}</div>
                        <div class="label">Unique Compartments</div>
                    </div>
                    <div class="stat-badge">
                        <div class="value">{n_proteins_with}</div>
                        <div class="label">Proteins with Location Data</div>
                    </div>
                    <div class="stat-badge">
                        <div class="value">{avg_locs}</div>
                        <div class="label">Avg Locations per Protein</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                @st.fragment
                def _loc_filter_fragment():
                    # --- Location filter ---
                    col_filter, col_mode = st.columns([4, 1])
                    with col_filter:
                        selected_locs = st.multiselect(
                            "Filter by compartment",
                            options=all_locations,
                            default=[],
                            key="loc_filter",
                            placeholder="Select compartments to filter proteins...",
                        )
                    with col_mode:
                        filter_mode = st.radio(
                            "Match mode",
                            ["ANY (OR)", "ALL (AND)"],
                            key="loc_mode",
                            help="ANY = protein in at least one selected location. "
                                 "ALL = protein in every selected location.",
                        )

                    if selected_locs:
                        # Filter proteins
                        if filter_mode == "ANY (OR)":
                            matched_proteins = loc_df[
                                loc_df["Location"].isin(selected_locs)
                            ]["Protein"].unique()
                        else:
                            # AND: protein must appear in ALL selected locations
                            protein_loc_sets = loc_df.groupby("Protein")["Location"].apply(set)
                            sel_set = set(selected_locs)
                            matched_proteins = [
                                p for p, locs in protein_loc_sets.items()
                                if sel_set.issubset(locs)
                            ]

                        filtered_df = result_df[
                            result_df[id_col_name].isin(matched_proteins)
                        ]

                        st.success(
                            f"**{len(matched_proteins)}** protein(s) match the "
                            f"selected compartment(s) ({filter_mode})"
                        )

                        st.dataframe(
                            filtered_df,
                            width='stretch',
                            height=min(38 * len(filtered_df) + 60, 500),
                        )

                        # CSV download for filtered set
                        filt_csv = filtered_df.to_csv(index=False).encode("utf-8")
                        st.download_button(
                            "⬇️  Download Filtered Proteins",
                            data=filt_csv,
                            file_name="paia_filtered_by_localization.csv",
                            mime="text/csv",
                        )
                    else:
                        st.caption("Select one or more compartments above to filter proteins.")

                    # --- Compartment distribution chart ---
                    st.markdown("---")
                    st.markdown("##### Compartment Distribution (all proteins)")

                    loc_counts = loc_df["Location"].value_counts()
                    # Group small categories if >15
                    if len(loc_counts) > 15:
                        top = loc_counts.head(14)
                        other = loc_counts.iloc[14:].sum()
                        loc_counts = pd.concat([top, pd.Series({"Other": other})])

                    fig = plot_pie(
                        pd.DataFrame({"Location": loc_df["Location"]}),
                        "Location",
                        title="Protein Compartment Distribution",
                    )
                    st.plotly_chart(fig, width='stretch', key="loc_pie")

                _loc_filter_fragment()

    # ── Biological Classification Explorer ────────────────────────────
    elif has_bio and active_section == "🧬 Classification Explorer":
            id_col_name = "Query ID" if "Query ID" in result_df.columns else "Accession"
            name_col = "Protein Name" if "Protein Name" in result_df.columns else None

            st.markdown("""
            <div class="card">
                <h3>Biological Classification Explorer</h3>
                <p style="color: var(--text-muted); font-size:0.88rem; margin:0;">
                    Explore how your proteins are classified across functional categories.
                    A protein can belong to multiple classes simultaneously.
                </p>
            </div>
            """, unsafe_allow_html=True)

            # --- Build class membership summary ---
            class_counts = {}
            for cls in bio_cols:
                count = result_df[cls].apply(
                    lambda v: v is True or v == 1 or str(v).lower() == "true"
                ).sum()
                class_counts[cls] = int(count)

            total_proteins = len(result_df)
            classified = sum(
                1 for _, row in result_df.iterrows()
                if any(
                    row.get(c) is True or row.get(c) == 1
                    or str(row.get(c, "")).lower() == "true"
                    for c in bio_cols
                )
            )
            avg_classes = 0.0
            if total_proteins > 0:
                per_protein = [
                    sum(
                        1 for c in bio_cols
                        if (row.get(c) is True or row.get(c) == 1
                            or str(row.get(c, "")).lower() == "true")
                    )
                    for _, row in result_df.iterrows()
                ]
                avg_classes = round(sum(per_protein) / total_proteins, 1)

            # --- Summary badges ---
            st.markdown(f"""
            <div class="stat-row">
                <div class="stat-badge">
                    <div class="value">{len(bio_cols)}</div>
                    <div class="label">Classes Annotated</div>
                </div>
                <div class="stat-badge">
                    <div class="value">{classified}</div>
                    <div class="label">Proteins Classified</div>
                </div>
                <div class="stat-badge">
                    <div class="value">{avg_classes}</div>
                    <div class="label">Avg Classes per Protein</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # --- Class distribution bar chart ---
            st.markdown("##### Class Distribution")
            counts_df = pd.DataFrame({
                "Class": list(class_counts.keys()),
                "Count": list(class_counts.values()),
            }).sort_values("Count", ascending=True)

            import plotly.graph_objects as go
            bar_fig = go.Figure(data=[go.Bar(
                y=counts_df["Class"],
                x=counts_df["Count"],
                orientation="h",
                marker=dict(
                    color=counts_df["Count"],
                    colorscale=[[0, "#1a1d29"], [0.5, "#5ce1e6"], [1, "#a855f7"]],
                    line=dict(color="#5ce1e6", width=1),
                ),
                text=counts_df["Count"],
                textposition="outside",
                textfont=dict(color="#e2e8f0", size=12),
                hovertemplate="<b>%{y}</b><br>Count: %{x}<extra></extra>",
            )])
            bar_fig.update_layout(
                paper_bgcolor="#0e1117",
                plot_bgcolor="#1a1d29",
                font=dict(family="Inter, sans-serif", color="#e2e8f0", size=13),
                margin=dict(l=160, r=60, t=20, b=40),
                xaxis=dict(
                    title="Number of Proteins",
                    gridcolor="rgba(92, 225, 230, 0.08)",
                    zeroline=False,
                ),
                yaxis=dict(gridcolor="rgba(92, 225, 230, 0.08)"),
                height=max(300, len(bio_cols) * 38 + 60),
            )
            st.plotly_chart(bar_fig, width='stretch', key="bio_bar")

            @st.fragment
            def _bio_filter_fragment():
                # --- Filter by class ---
                st.markdown("---")
                st.markdown("##### Filter Proteins by Class")

                col_filter, col_mode = st.columns([4, 1])
                with col_filter:
                    selected_classes = st.multiselect(
                        "Select biological classes",
                        options=bio_cols,
                        default=[],
                        key="bio_filter",
                        placeholder="Select classes to filter proteins...",
                    )
                with col_mode:
                    bio_filter_mode = st.radio(
                        "Match mode",
                        ["ANY (OR)", "ALL (AND)"],
                        key="bio_mode",
                        help="ANY = protein belongs to at least one selected class. "
                             "ALL = protein belongs to every selected class.",
                    )

                if selected_classes:
                    def _is_true(val):
                        return val is True or val == 1 or str(val).lower() == "true"

                    if bio_filter_mode == "ANY (OR)":
                        mask = result_df[selected_classes].apply(
                            lambda row: any(_is_true(v) for v in row), axis=1
                        )
                    else:
                        mask = result_df[selected_classes].apply(
                            lambda row: all(_is_true(v) for v in row), axis=1
                        )

                    bio_filtered_df = result_df[mask]

                    st.success(
                        f"**{len(bio_filtered_df)}** protein(s) match the "
                        f"selected class(es) ({bio_filter_mode})"
                    )

                    # Show classification overview for filtered proteins
                    display_cols = [id_col_name]
                    if name_col:
                        display_cols.append(name_col)
                    display_cols.extend(selected_classes)
                    show_df = bio_filtered_df[display_cols].copy()

                    # Replace True/False with emoji for readability
                    for cls in selected_classes:
                        show_df[cls] = show_df[cls].apply(
                            lambda v: "✅" if _is_true(v) else "❌"
                        )

                    st.dataframe(
                        show_df,
                        width='stretch',
                        height=min(38 * len(show_df) + 60, 500),
                    )

                    # CSV download
                    bio_csv = bio_filtered_df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "⬇️  Download Filtered Proteins",
                        data=bio_csv,
                        file_name="paia_filtered_by_classification.csv",
                        mime="text/csv",
                        key="bio_download",
                    )
                else:
                    st.caption("Select one or more classes above to filter proteins.")

            _bio_filter_fragment()

    # ── Download ──────────────────────────────────────────────────────
    st.markdown("---")

    snapshot = st.session_state.run_snapshot
    export_df = merge_annotations(snapshot["input_frame"], snapshot["id_col"], full_result_df)
    csv_bytes = export_df.to_csv(index=False).encode("utf-8-sig")
    filtered_ids = set(result_df["Query ID"])
    filtered_input = snapshot["input_frame"][snapshot["input_frame"][snapshot["id_col"]].fillna("").astype(str).str.strip().isin(filtered_ids)]
    filtered_export = merge_annotations(filtered_input, snapshot["id_col"], result_df)
    st.download_button("Download filtered CSV", filtered_export.to_csv(index=False).encode("utf-8-sig"),
                       file_name="paia_filtered_proteins.csv", mime="text/csv", key="download_combined")

    dcol1, dcol2, dcol3 = st.columns([1, 2, 1])
    with dcol2:
        st.download_button(
            label="⬇️  Download Annotated CSV",
            data=csv_bytes,
            file_name="paia_annotated_proteins.csv",
            mime="text/csv",
            use_container_width=True,
        )

else:
    # ── Welcome / empty state ─────────────────────────────────────────
    st.markdown("""
    <div class="card" style="text-align:center; padding:3rem;">
        <h3 style="font-size:1.3rem;">Welcome to the PAIA Engine</h3>
        <p style="color: var(--text-muted); max-width:600px; margin:auto;">
            Upload a CSV/TSV file or type protein IDs in the sidebar,
            select the attributes you want to retrieve, then click
            <strong>🚀 Annotate Proteins</strong> to begin.
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Quick-start demo
    with st.expander("🧪 Quick Demo — Try these example IDs"):
        st.code(
            "P04637\nACTB\nGAPDH\nP00533\nTP53",
            language=None,
        )
        st.caption(
            "Copy the IDs above, switch to *⌨️ Type Protein IDs* mode in the sidebar, "
            "paste them in, then click **🚀 Annotate Proteins**. "
            "You can use UniProt accession IDs (P04637) or gene symbols (ACTB, TP53)."
        )
