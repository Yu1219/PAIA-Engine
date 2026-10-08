"""Evidence-preserving GO, domain, PTM and membrane annotations.

Coordinates are UniProt/InterPro 1-based inclusive coordinates. Stored evidence
is source evidence, not a confidence score or a claim of experimental proof.
"""
from datetime import datetime, timezone

NEW_CATEGORIES = {
    "GO / Domains": ["GO Molecular Function", "GO Biological Process", "GO Cellular Component",
                     "Protein Domains", "Protein Families", "InterPro Entries", "Pfam Entries"],
    "PTM Details": ["PTM Details", "Lipidation Sites", "Glycoprotein Annotation"],
    "Membrane / Surface": ["Membrane Location", "Extracellular Regions", "Cell Surface Candidate"],
}
PTM_TYPES = {"Modified residue", "Glycosylation", "Lipidation", "Disulfide bond", "Cross-link"}
FEATURE_ATTRIBUTES = {
    "Zinc-Binding Sites": {"Zinc finger", "Binding site"}, "Metal-Binding Sites": {"Metal binding", "Binding site"},
    "Phosphorylation Sites": {"Modified residue"}, "Disulfide Bonds": {"Disulfide bond"},
    "Glycosylation Sites": {"Glycosylation"}, "Signal Peptide": {"Signal peptide"},
    "Transmembrane Regions": {"Transmembrane"}, "DNA-Binding Domains": {"DNA binding"},
    "Active Sites": {"Active site"}, "Coiled-Coil Regions": {"Coiled coil"},
    "Topological Domains": {"Topological domain"}, "Extracellular Regions": {"Topological domain"},
    "Lipidation Sites": {"Lipidation"}, "PTM Details": PTM_TYPES, "Protein Domains": {"Domain"},
}
BOOLEAN_ATTRIBUTES = {
    "Kinase Activity", "Signal Peptide", "Receptor", "Secreted Protein", "Cell Adhesion",
    "Transporter / Channel", "Enzyme", "Transcription Factor", "Protease", "Cytokine / Growth Factor",
    "Structural Protein", "Immune-Related", "Cell Surface Candidate", "Glycoprotein Annotation",
}
CLASSIFICATION_ATTRIBUTES = BOOLEAN_ATTRIBUTES - {"Signal Peptide", "Cell Surface Candidate", "Glycoprotein Annotation"}


def joined(values):
    return "; ".join(dict.fromkeys(str(v) for v in values if v)) or None


def evidence_text(evidences):
    return joined(e.get("evidenceCode") or e.get("code") or e.get("value") for e in evidences or [])


def reference_text(evidences):
    return joined(f"{e.get('source', 'Source')}:{e['id']}" for e in evidences or [] if e.get("id"))


def position(feature):
    loc = feature.get("location", {})
    def point(key):
        p = loc.get(key, {})
        if isinstance(p, int):
            return p
        val = p.get("value")
        return str(val) + "?" if val is not None and p.get("modifier", "EXACT") != "EXACT" else val
    return point("start"), point("end"), loc.get("sequence") or "Canonical sequence"


def feature_label(feature):
    start, end, sequence = position(feature)
    coord = str(start) if start == end else f"{start}-{end}"
    return f"{feature.get('description') or feature.get('type')} [{coord}; {sequence}]"


def record(attr, value, source="UniProt", method="Database annotation", evidences=None, **extra):
    return {"Attribute": attr, "Value": value, "Source": source, "Method": method,
            "Evidence": evidence_text(evidences), "References": reference_text(evidences), **extra}


def go_records(entry):
    records = []
    aspects = {"F": "GO Molecular Function", "P": "GO Biological Process", "C": "GO Cellular Component"}
    for ref in entry.get("uniProtKBCrossReferences", []):
        if ref.get("database") != "GO":
            continue
        props = {p.get("key"): p.get("value", "") for p in ref.get("properties", [])}
        term = props.get("GoTerm", "")
        if len(term) < 2 or term[0] not in aspects:
            continue
        rec = record(aspects[term[0]], f"{ref['id']} | {term[2:]}", source="GO via UniProt",
                     evidences=ref.get("evidences"), URL=f"https://www.ebi.ac.uk/QuickGO/term/{ref['id']}")
        rec["Evidence"] = joined([props.get("GoEvidenceType"), rec["Evidence"]])
        records.append(rec)
    return records


def interpro_records(payload):
    records = []
    for result in (payload or {}).get("results", []):
        meta = result.get("metadata", {})
        acc = meta.get("accession", "")
        name = meta.get("name", acc)
        kind = meta.get("type", "").lower()
        attr = "Protein Families" if kind == "family" else "Protein Domains" if kind == "domain" else "InterPro Entries"
        fragments = []
        for protein in result.get("proteins", []):
            for location in protein.get("entry_protein_locations", []):
                fragments.extend(location.get("fragments", []))
        for fragment in fragments or [{}]:
            records.append(record(attr, f"{acc} | {name}", source="InterPro",
                                  method=f"InterPro {kind or 'entry'} annotation", Start=fragment.get("start"),
                                  End=fragment.get("end"), Sequence="Canonical sequence",
                                  URL=f"https://www.ebi.ac.uk/interpro/entry/InterPro/{acc}/"))
    return records


def canonical_locations(entry):
    """Use unscoped or displayed-isoform locations for canonical surface inference."""
    displayed = set()
    for comment in entry.get("comments", []):
        if comment.get("commentType") == "ALTERNATIVE PRODUCTS":
            for isoform in comment.get("isoforms", []):
                if isoform.get("isoformSequenceStatus") == "Displayed":
                    displayed.add("Isoform " + isoform.get("name", {}).get("value", ""))
    return [c for c in entry.get("comments", []) if c.get("commentType") == "SUBCELLULAR LOCATION"
            and (not c.get("molecule") or c.get("molecule") in displayed)]


def membrane_info(entry):
    locations = []
    for comment in canonical_locations(entry):
        locations.extend(s.get("location", {}).get("value", "") for s in comment.get("subcellularLocations", []))
    cell_membrane = any(v.lower() in {"cell membrane", "plasma membrane", "cell surface"} for v in locations)
    internal = any("membrane" in v.lower() and v.lower() not in {"cell membrane", "plasma membrane", "membrane"} for v in locations)
    unspecified = any(v.lower() == "membrane" for v in locations)
    extracellular = [f for f in entry.get("features", []) if f.get("type") == "Topological domain"
                     and not f.get("location", {}).get("sequence") and f.get("description", "").lower() == "extracellular"]
    anchor = any(f.get("type") == "Lipidation" and "gpi" in f.get("description", "").lower()
                 for f in entry.get("features", []) if not f.get("location", {}).get("sequence"))
    # A lumenal domain or generic membrane annotation is insufficient for a cell-surface call.
    labels = (["Cell / plasma membrane"] if cell_membrane else []) + (["Intracellular membrane"] if internal else [])
    if unspecified:
        labels.append("Membrane (unspecified)")
    return joined(labels), extracellular, True if cell_membrane and (extracellular or anchor) else None


def add_annotations(entry, selected_attrs, result, interpro=None, retrieved_at=None, release=None):
    """Extend a parsed entry without losing source records or coordinate context."""
    acc = entry.get("primaryAccession")
    result.update({"Protein Name": entry.get("proteinDescription", {}).get("recommendedName", {}).get("fullName", {}).get("value"),
                   "Gene Name": next((g.get("geneName", {}).get("value") for g in entry.get("genes", []) if g.get("geneName")), None),
                   "Organism": entry.get("organism", {}).get("scientificName"),
                   "Taxonomy ID": entry.get("organism", {}).get("taxonId"),
                   "Reviewed": entry.get("entryType") == "UniProtKB reviewed (Swiss-Prot)",
                   "Entry Version": entry.get("entryAudit", {}).get("entryVersion"),
                   "Retrieved At": retrieved_at or datetime.now(timezone.utc).isoformat(),
                   "UniProt Release": release, "UniProt URL": f"https://www.uniprot.org/uniprotkb/{acc}/entry"})
    result["Annotation Scope"] = "Canonical sequence coordinates; entry-level classification; isoform-specific evidence retained"
    records = go_records(entry)
    records.extend(interpro_records(interpro))
    refs = entry.get("uniProtKBCrossReferences", [])
    values = {"InterPro Entries": joined(f"{r['id']} | " + next((p['value'] for p in r.get('properties', []) if p.get('key') == 'EntryName'), '')
                                         for r in refs if r.get('database') == 'InterPro'),
              "Pfam Entries": joined(f"{r['id']} | " + next((p['value'] for p in r.get('properties', []) if p.get('key') == 'EntryName'), '')
                                     for r in refs if r.get('database') == 'Pfam')}
    for attr in ("GO Molecular Function", "GO Biological Process", "GO Cellular Component", "Protein Domains", "Protein Families"):
        values[attr] = joined(r["Value"] for r in records if r["Attribute"] == attr)
    for attr, value in values.items():
        if attr in selected_attrs:
            result[attr] = value
    for attr, kinds in FEATURE_ATTRIBUTES.items():
        if attr not in selected_attrs:
            continue
        features = [f for f in entry.get("features", []) if f.get("type") in kinds]
        if attr == "Phosphorylation Sites":
            features = [f for f in features if "phospho" in f.get("description", "").lower()]
        if attr == "Extracellular Regions":
            features = [f for f in features if f.get("description", "").lower() == "extracellular"]
        if attr == "Metal-Binding Sites":
            metals = ("metal", "iron", "calcium", "magnesium", "manganese", "copper", "cobalt", "zinc", "nickel")
            features = [f for f in features if f.get("type") == "Metal binding" or any(m in (f.get("description", "") + " " + f.get("ligand", {}).get("name", "")).lower() for m in metals)]
        if attr == "Zinc-Binding Sites":
            features = [f for f in features if f.get("type") == "Zinc finger" or "zinc" in (f.get("description", "") + " " + f.get("ligand", {}).get("name", "")).lower()]
        for feature in features:
            start, end, sequence = position(feature)
            records.append(record(attr, feature.get("description") or feature.get("type"), evidences=feature.get("evidences"),
                                  Start=start, End=end, Sequence=sequence, URL=result["UniProt URL"]))
        if attr in {"PTM Details", "Extracellular Regions"}:
            result[attr] = joined(feature_label(f) for f in features)
        elif attr == "Protein Domains":
            result[attr] = joined([result.get(attr)] + [feature_label(f) for f in features])
        elif attr == "Lipidation Sites":
            result[attr] = len(features)
    if "Protein Families" in selected_attrs:
        # UniProt SIMILARITY text is preserved as text rather than retyped as an InterPro family.
        texts = [t for c in entry.get("comments", []) if c.get("commentType") == "SIMILARITY" for t in c.get("texts", [])]
        for t in texts:
            records.append(record("Protein Families", t.get("value"), evidences=t.get("evidences"), URL=result["UniProt URL"]))
        result["Protein Families"] = joined([result.get("Protein Families")] + [t.get("value") for t in texts])
    membrane, extracellular, surface = membrane_info(entry)
    if "Membrane Location" in selected_attrs:
        result["Membrane Location"] = membrane
    if "Cell Surface Candidate" in selected_attrs:
        result["Cell Surface Candidate"] = surface
        records.append(record("Cell Surface Candidate", "Supported candidate" if surface else "Insufficient supporting annotation",
                              method="Derived: cell/plasma membrane location AND extracellular topology or GPI anchor; does not establish accessibility",
                              URL=result["UniProt URL"]))
    if "Glycoprotein Annotation" in selected_attrs:
        result["Glycoprotein Annotation"] = True if any(k.get("name", "").lower() == "glycoprotein" for k in entry.get("keywords", [])) else None
    for attr in selected_attrs:
        if attr in BOOLEAN_ATTRIBUTES and result.get(attr) is False:
            result[attr] = None  # Missing support is not evidence of a negative biological result.
        if attr in CLASSIFICATION_ATTRIBUTES:
            records.append(record(attr, "Supported by classification rule" if result.get(attr) is True else "No supporting annotation",
                                  method="Keyword/name/annotation rule (not an experimental assay)", URL=result["UniProt URL"]))
            for kw in entry.get("keywords", []):
                records.append(record(attr, kw.get("name"), method="Source keyword for inspection; not necessarily the matched rule",
                                      evidences=kw.get("evidences"), URL=result["UniProt URL"]))
            records.append(record(attr, result.get("Protein Name"), method="Source protein name for inspection", URL=result["UniProt URL"]))
    comment_attrs = {"FUNCTION": "Protein Function", "SUBCELLULAR LOCATION": "Subcellular Localization", "TISSUE SPECIFICITY": "Tissue Specificity", "CATALYTIC ACTIVITY": "Kinase Activity"}
    for comment in entry.get("comments", []):
        attr = comment_attrs.get(comment.get("commentType"))
        if attr not in selected_attrs and attr != "Subcellular Localization":
            continue
        for t in comment.get("texts", []):
            records.append(record(attr, t.get("value"), evidences=t.get("evidences"), URL=result["UniProt URL"]))
        for loc in comment.get("subcellularLocations", []):
            for key in ("location", "topology", "orientation"):
                item = loc.get(key, {})
                if item.get("value"):
                    records.append(record(attr, item["value"], evidences=item.get("evidences"), Sequence=comment.get("molecule") or "Canonical sequence", URL=result["UniProt URL"]))
    if "Isoelectric Point (pI)" in selected_attrs:
        records.append(record("Isoelectric Point (pI)", result.get("Isoelectric Point (pI)"), source="Local sequence calculation",
                              method="Theoretical pI: Henderson-Hasselbalch / Lehninger pKa; canonical unmodified sequence"))
    for attr in selected_attrs:
        if not any(r["Attribute"] == attr for r in records):
            records.append(record(attr, result.get(attr), method="Source field or annotation; absent support remains unannotated", URL=result["UniProt URL"]))
    result["_annotation_records"] = [r for r in records if r["Attribute"] in selected_attrs or r["Attribute"] == "Subcellular Localization"]
    result["_entry"] = entry
    return result
