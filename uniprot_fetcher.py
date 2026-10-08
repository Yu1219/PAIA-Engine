"""
uniprot_fetcher.py — Asynchronous batch retrieval from UniProt REST API.

Fetches protein annotations (physicochemical, functional/structural, spatial)
with semaphore-based rate-limiting, exponential back-off retries, and
graceful error handling.
"""

import asyncio
import aiohttp
from typing import Any
from annotation_details import add_annotations, NEW_CATEGORIES, BOOLEAN_ATTRIBUTES, CLASSIFICATION_ATTRIBUTES, record

# ─── Configuration ────────────────────────────────────────────────────
BASE_URL = "https://rest.uniprot.org/uniprotkb/search"
MAX_CONCURRENT = 10          # semaphore limit
INTER_REQUEST_DELAY = 0.12   # seconds between requests (polite throttle)
MAX_RETRIES = 3
BACKOFF_FACTOR = 1.5         # exponential back-off multiplier


# ─── Attribute parsers ───────────────────────────────────────────────

def _safe(fn, default=None):
    """Wrap a parser so it never raises."""
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception:
            return default
    return wrapper


@_safe
def _parse_molecular_weight(entry: dict) -> float | None:
    seq = entry.get("sequence", {})
    mw = seq.get("molWeight")
    return float(mw) if mw is not None else None


@_safe
def _parse_isoelectric_point(entry: dict) -> float | None:
    """Calculate theoretical pI; pH-dependence prose is not a measured pI field."""
    seq_str = entry.get("sequence", {}).get("value", "")
    if seq_str:
        return _compute_theoretical_pi(seq_str)
    return None


def _compute_theoretical_pi(sequence: str) -> float:
    """Compute theoretical isoelectric point using pKa values (Lehninger)."""
    pK = {
        "K": 10.5, "R": 12.4, "H": 6.0,
        "D": 3.65, "E": 4.25, "C": 8.18, "Y": 10.07,
        "N_term": 9.69, "C_term": 2.34,
    }
    pos_aa = {aa: sequence.count(aa) for aa in ("K", "R", "H")}
    neg_aa = {aa: sequence.count(aa) for aa in ("D", "E", "C", "Y")}

    def _charge(pH: float) -> float:
        c = 0.0
        # N-terminus
        c += 1.0 / (1.0 + 10 ** (pH - pK["N_term"]))
        # C-terminus
        c -= 1.0 / (1.0 + 10 ** (pK["C_term"] - pH))
        for aa, cnt in pos_aa.items():
            c += cnt / (1.0 + 10 ** (pH - pK[aa]))
        for aa, cnt in neg_aa.items():
            c -= cnt / (1.0 + 10 ** (pK[aa] - pH))
        return c

    lo, hi = 0.0, 14.0
    while hi - lo > 0.001:
        mid = (lo + hi) / 2.0
        if _charge(mid) > 0:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2.0, 2)


@_safe
def _parse_subcellular_location(entry: dict) -> str | None:
    locs = []
    for comment in entry.get("comments", []):
        if comment.get("commentType") == "SUBCELLULAR LOCATION":
            for sub in comment.get("subcellularLocations", []):
                loc = sub.get("location", {})
                val = loc.get("value")
                if val:
                    locs.append(val)
    # Deduplicate while preserving order
    seen = dict.fromkeys(locs)
    return "; ".join(seen) if seen else None


@_safe
def _parse_kinase_activity(entry: dict) -> bool:
    """True if protein has kinase-related keywords or catalytic activity."""
    keywords = [kw.get("name", "").lower() for kw in entry.get("keywords", [])]
    if any("kinase" in kw for kw in keywords):
        return True
    for comment in entry.get("comments", []):
        if comment.get("commentType") == "CATALYTIC ACTIVITY":
            rxn = comment.get("reaction", {})
            name = rxn.get("name", "") or ""
            if "kinase" in name.lower() or "phosphotransferase" in name.lower():
                return True
    # Also check protein names
    desc = entry.get("proteinDescription", {})
    rec = desc.get("recommendedName", {})
    full = rec.get("fullName", {}).get("value", "")
    if "kinase" in full.lower():
        return True
    return False


@_safe
def _parse_zinc_binding(entry: dict) -> int:
    count = 0
    for feat in entry.get("features", []):
        if feat.get("type") == "Zinc finger" or (
            feat.get("type") == "Binding site"
            and "zinc" in feat.get("description", "").lower()
        ):
            count += 1
    return count


@_safe
def _parse_metal_binding(entry: dict) -> int:
    count = 0
    for feat in entry.get("features", []):
        if feat.get("type") in ("Metal binding", "Binding site"):
            desc = (feat.get("description", "") + " " + feat.get("ligand", {}).get("name", "")).lower()
            if any(m in desc for m in ("metal", "iron", "calcium", "magnesium",
                                        "manganese", "copper", "cobalt", "zinc",
                                        "nickel")):
                count += 1
        if feat.get("type") == "Metal binding" and not any(m in desc for m in ("metal", "iron", "calcium", "magnesium", "manganese", "copper", "cobalt", "zinc", "nickel")):
            count += 1
    return count


@_safe
def _parse_phosphorylation_sites(entry: dict) -> int:
    count = 0
    for feat in entry.get("features", []):
        if feat.get("type") == "Modified residue":
            desc = feat.get("description", "").lower()
            if "phospho" in desc:
                count += 1
    return count


@_safe
def _parse_protein_name(entry: dict) -> str | None:
    desc = entry.get("proteinDescription", {})
    rec = desc.get("recommendedName", {})
    full = rec.get("fullName", {})
    if isinstance(full, dict):
        return full.get("value")
    # Fallback to submittedName
    for sub in desc.get("submissionNames", desc.get("alternativeNames", [])):
        fn = sub.get("fullName", {})
        if isinstance(fn, dict):
            return fn.get("value")
    return None


@_safe
def _parse_gene_name(entry: dict) -> str | None:
    genes = entry.get("genes", [])
    if genes:
        return genes[0].get("geneName", {}).get("value")
    return None


@_safe
def _parse_organism(entry: dict) -> str | None:
    org = entry.get("organism", {})
    return org.get("scientificName")


@_safe
def _parse_sequence_length(entry: dict) -> int | None:
    return entry.get("sequence", {}).get("length")


# ─── NEW Functional / Structural parsers ──────────────────────────────

@_safe
def _parse_disulfide_bonds(entry: dict) -> int:
    count = 0
    for feat in entry.get("features", []):
        if feat.get("type") == "Disulfide bond":
            count += 1
    return count


@_safe
def _parse_glycosylation_sites(entry: dict) -> int:
    count = 0
    for feat in entry.get("features", []):
        if feat.get("type") == "Glycosylation":
            count += 1
    return count


@_safe
def _parse_signal_peptide(entry: dict) -> bool:
    for feat in entry.get("features", []):
        if feat.get("type") == "Signal peptide":
            return True
    return False


@_safe
def _parse_transmembrane_regions(entry: dict) -> int:
    count = 0
    for feat in entry.get("features", []):
        if feat.get("type") == "Transmembrane":
            count += 1
    return count


@_safe
def _parse_dna_binding(entry: dict) -> int:
    count = 0
    for feat in entry.get("features", []):
        if feat.get("type") == "DNA binding":
            count += 1
    return count


@_safe
def _parse_active_sites(entry: dict) -> int:
    count = 0
    for feat in entry.get("features", []):
        if feat.get("type") == "Active site":
            count += 1
    return count


@_safe
def _parse_coiled_coil(entry: dict) -> int:
    count = 0
    for feat in entry.get("features", []):
        if feat.get("type") == "Coiled coil":
            count += 1
    return count


# ─── NEW Spatial parsers ──────────────────────────────────────────────

@_safe
def _parse_tissue_specificity(entry: dict) -> str | None:
    for comment in entry.get("comments", []):
        if comment.get("commentType") == "TISSUE SPECIFICITY":
            texts = comment.get("texts", [])
            parts = []
            for t in texts:
                val = t if isinstance(t, str) else t.get("value", "")
                if val:
                    parts.append(val)
            return " ".join(parts) if parts else None
    return None


@_safe
def _parse_topological_domains(entry: dict) -> str | None:
    domains = []
    for feat in entry.get("features", []):
        if feat.get("type") == "Topological domain":
            desc = feat.get("description", "")
            if desc and desc not in domains:
                domains.append(desc)
    return "; ".join(domains) if domains else None


# ─── Biological Classification parsers ────────────────────────────────

def _get_keywords_lower(entry: dict) -> list[str]:
    """Helper: return all keyword names in lowercase."""
    return [kw.get("name", "").lower() for kw in entry.get("keywords", [])]


def _get_protein_name_lower(entry: dict) -> str:
    """Helper: return the recommended protein name in lowercase."""
    desc = entry.get("proteinDescription", {})
    rec = desc.get("recommendedName", {})
    full = rec.get("fullName", {})
    name = full.get("value", "") if isinstance(full, dict) else ""
    return name.lower()


@_safe
def _parse_is_receptor(entry: dict) -> bool:
    kws = _get_keywords_lower(entry)
    name = _get_protein_name_lower(entry)
    if any("receptor" in k for k in kws):
        return True
    if "receptor" in name:
        return True
    return False


@_safe
def _parse_is_secreted(entry: dict) -> bool:
    kws = _get_keywords_lower(entry)
    name = _get_protein_name_lower(entry)
    if "secreted" in kws:
        return True
    if "secreted" in name:
        return True
    # Check subcellular location for "Secreted"
    for comment in entry.get("comments", []):
        if comment.get("commentType") == "SUBCELLULAR LOCATION":
            for sub in comment.get("subcellularLocations", []):
                val = sub.get("location", {}).get("value", "").lower()
                if "secreted" in val:
                    return True
    return False


@_safe
def _parse_is_adhesion(entry: dict) -> bool:
    kws = _get_keywords_lower(entry)
    name = _get_protein_name_lower(entry)
    if any(k in ("cell adhesion", "cell junction") for k in kws):
        return True
    if any(t in name for t in ("adhesion", "integrin", "cadherin",
                                "selectin", "icam", "vcam", "pecam")):
        return True
    return False


@_safe
def _parse_is_transporter(entry: dict) -> bool:
    kws = _get_keywords_lower(entry)
    name = _get_protein_name_lower(entry)
    if any(k in ("transport", "ion transport", "ion channel",
                  "voltage-gated channel", "symport", "antiport",
                  "sodium channel", "potassium channel", "calcium channel",
                  "chloride channel", "transporter") for k in kws):
        return True
    if any(t in name for t in ("transporter", "channel", "exchanger",
                                "pump", "carrier", "solute carrier")):
        return True
    return False


@_safe
def _parse_is_enzyme(entry: dict) -> bool:
    # EC number in protein description indicates enzyme
    desc = entry.get("proteinDescription", {})
    rec = desc.get("recommendedName", {})
    ec_nums = rec.get("ecNumbers", [])
    if ec_nums:
        return True
    kws = _get_keywords_lower(entry)
    enzyme_kws = {"oxidoreductase", "transferase", "hydrolase", "lyase",
                  "isomerase", "ligase", "protease", "kinase", "phosphatase",
                  "dehydrogenase", "synthase", "synthetase"}
    if any(k in enzyme_kws for k in kws):
        return True
    name = _get_protein_name_lower(entry)
    if any(t in name for t in ("ase ", "ase,", "ase-")):
        return True
    return False


@_safe
def _parse_is_transcription_factor(entry: dict) -> bool:
    kws = _get_keywords_lower(entry)
    name = _get_protein_name_lower(entry)
    if any("transcription factor" in k for k in kws):
        return True
    if any(t in name for t in ("transcription factor", "homeobox")):
        return True
    for ref in entry.get("uniProtKBCrossReferences", []):
        if ref.get("database") == "GO" and any("DNA-binding transcription factor activity" in p.get("value", "") for p in ref.get("properties", [])):
            return True
    return False


@_safe
def _parse_is_protease(entry: dict) -> bool:
    kws = _get_keywords_lower(entry)
    name = _get_protein_name_lower(entry)
    if any(k in ("protease", "metalloprotease", "serine protease",
                  "cysteine protease", "aspartyl protease",
                  "threonine protease") for k in kws):
        return True
    if any(t in name for t in ("protease", "proteinase", "peptidase",
                                "caspase", "cathepsin", "metalloproteinase",
                                "convertase")):
        return True
    return False


@_safe
def _parse_is_cytokine(entry: dict) -> bool:
    kws = _get_keywords_lower(entry)
    name = _get_protein_name_lower(entry)
    if any(k in ("cytokine", "growth factor", "chemokine") for k in kws):
        return True
    if any(t in name for t in ("cytokine", "interleukin", "interferon",
                                "growth factor", "chemokine", "tumor necrosis",
                                "colony-stimulating")):
        return True
    return False


@_safe
def _parse_is_structural(entry: dict) -> bool:
    kws = _get_keywords_lower(entry)
    name = _get_protein_name_lower(entry)
    if any(k in ("structural protein", "cytoskeleton", "intermediate filament",
                  "collagen", "extracellular matrix") for k in kws):
        return True
    if any(t in name for t in ("collagen", "actin", "tubulin", "keratin",
                                "vimentin", "lamin", "fibronectin",
                                "elastin", "myosin")):
        return True
    return False


@_safe
def _parse_is_immune(entry: dict) -> bool:
    kws = _get_keywords_lower(entry)
    name = _get_protein_name_lower(entry)
    if any(k in ("immune response", "innate immunity", "adaptive immunity",
                  "complement pathway", "immunoglobulin domain", "mhc",
                  "antigen", "inflammatory response") for k in kws):
        return True
    if any(t in name for t in ("immunoglobulin", "antibody", "complement",
                                "mhc", "hla-", "toll-like", "nf-kappa",
                                "defensin", "lysozyme")):
        return True
    return False


@_safe
def _parse_function(entry: dict) -> str | None:
    """Extract the protein's functional description from FUNCTION comment."""
    for comment in entry.get("comments", []):
        if comment.get("commentType") == "FUNCTION":
            texts = comment.get("texts", [])
            parts = []
            for t in texts:
                val = t if isinstance(t, str) else t.get("value", "")
                if val:
                    parts.append(val)
            return " ".join(parts) if parts else None
    return None


# ─── Attribute source descriptions ────────────────────────────────────

ATTRIBUTE_SOURCES: dict[str, str] = {
    # Physicochemical
    "Molecular Weight (Da)":
        "UniProt sequence.molWeight field (calculated from amino acid composition).",
    "Isoelectric Point (pI)":
        "Calculated theoretical pI from the canonical unmodified sequence (Henderson-Hasselbalch, Lehninger pKa); not measured pI.",
    "Sequence Length":
        "UniProt sequence.length field.",
    # Functional / Structural
    "Kinase Activity":
        "UniProt keywords containing 'kinase', CATALYTIC ACTIVITY comments, or protein name.",
    "Zinc-Binding Sites":
        "Count of registered UniProt 'Zinc finger' or zinc 'Binding site' features. Zero means no registered features.",
    "Metal-Binding Sites":
        "UniProt features of type 'Metal binding' or 'Binding site' mentioning metal ions (Fe, Ca, Mg, Mn, Cu, etc.).",
    "Phosphorylation Sites":
        "UniProt features of type 'Modified residue' with 'phospho' in the description.",
    "Disulfide Bonds":
        "UniProt features of type 'Disulfide bond'.",
    "Glycosylation Sites":
        "Count of registered UniProt 'Glycosylation' features; keyword alone does not establish a site count.",
    "Signal Peptide":
        "UniProt features of type 'Signal peptide'.",
    "Transmembrane Regions":
        "UniProt features of type 'Transmembrane'.",
    "DNA-Binding Domains":
        "UniProt features of type 'DNA binding'.",
    "Active Sites":
        "UniProt features of type 'Active site'.",
    "Coiled-Coil Regions":
        "UniProt features of type 'Coiled coil'.",
    # Biological Classification
    "Receptor":
        "UniProt keywords or protein name containing 'receptor'.",
    "Secreted Protein":
        "UniProt keyword/location 'Secreted', or name containing 'secreted'; a signal peptide alone is insufficient.",
    "Cell Adhesion":
        "UniProt keywords 'Cell adhesion'/'Cell junction'; protein name containing integrin, cadherin, selectin, ICAM, etc.",
    "Transporter / Channel":
        "UniProt keywords (ion transport, ion channel, symport, antiport, etc.) or protein name (transporter, channel, pump, carrier).",
    "Enzyme":
        "Presence of EC number in protein description, or UniProt keywords (oxidoreductase, transferase, hydrolase, etc.), or '-ase' suffix in protein name.",
    "Transcription Factor":
        "Specific transcription-factor name/keyword or DNA-binding transcription-factor GO activity; generic transcription or zinc-finger annotation is insufficient.",
    "Protease":
        "UniProt keywords (protease, metalloprotease, serine/cysteine/aspartyl protease) or protein name (caspase, cathepsin, peptidase, etc.).",
    "Cytokine / Growth Factor":
        "UniProt keywords (cytokine, growth factor, chemokine) or protein name (interleukin, interferon, TNF, colony-stimulating).",
    "Structural Protein":
        "UniProt keywords (structural protein, cytoskeleton, collagen, ECM) or protein name (actin, tubulin, keratin, vimentin, etc.).",
    "Immune-Related":
        "UniProt keywords (immune response, innate/adaptive immunity, complement, MHC, antigen) or protein name (immunoglobulin, HLA, toll-like, defensin).",
    # Spatial
    "Subcellular Localization":
        "UniProt SUBCELLULAR LOCATION comments (location values, deduplicated).",
    "Tissue Specificity":
        "UniProt TISSUE SPECIFICITY comment text.",
    "Topological Domains":
        "UniProt features of type 'Topological domain' (e.g., Extracellular, Cytoplasmic).",
    # General Info
    "Protein Name":
        "UniProt proteinDescription.recommendedName.fullName.",
    "Gene Name":
        "UniProt genes[0].geneName.",
    "Organism":
        "UniProt organism.scientificName.",
    "Protein Function":
        "UniProt FUNCTION comment text.",
}


# ─── Master parser ────────────────────────────────────────────────────

# Maps user-facing attribute name -> parser function
ATTRIBUTE_PARSERS: dict[str, Any] = {
    # Physicochemical
    "Molecular Weight (Da)":      _parse_molecular_weight,
    "Isoelectric Point (pI)":     _parse_isoelectric_point,
    "Sequence Length":             _parse_sequence_length,
    # Functional / Structural
    "Kinase Activity":            _parse_kinase_activity,
    "Zinc-Binding Sites":         _parse_zinc_binding,
    "Metal-Binding Sites":        _parse_metal_binding,
    "Phosphorylation Sites":      _parse_phosphorylation_sites,
    "Disulfide Bonds":            _parse_disulfide_bonds,
    "Glycosylation Sites":        _parse_glycosylation_sites,
    "Signal Peptide":             _parse_signal_peptide,
    "Transmembrane Regions":      _parse_transmembrane_regions,
    "DNA-Binding Domains":        _parse_dna_binding,
    "Active Sites":               _parse_active_sites,
    "Coiled-Coil Regions":        _parse_coiled_coil,
    # Biological Classification
    "Receptor":                   _parse_is_receptor,
    "Secreted Protein":           _parse_is_secreted,
    "Cell Adhesion":              _parse_is_adhesion,
    "Transporter / Channel":      _parse_is_transporter,
    "Enzyme":                     _parse_is_enzyme,
    "Transcription Factor":       _parse_is_transcription_factor,
    "Protease":                   _parse_is_protease,
    "Cytokine / Growth Factor":   _parse_is_cytokine,
    "Structural Protein":         _parse_is_structural,
    "Immune-Related":             _parse_is_immune,
    # Spatial
    "Subcellular Localization":   _parse_subcellular_location,
    "Tissue Specificity":         _parse_tissue_specificity,
    "Topological Domains":        _parse_topological_domains,
    # Meta
    "Protein Name":               _parse_protein_name,
    "Gene Name":                  _parse_gene_name,
    "Organism":                   _parse_organism,
    "Protein Function":           _parse_function,
}

# Attribute categories for the GUI
ATTRIBUTE_CATEGORIES: dict[str, list[str]] = {
    "Physicochemical": [
        "Molecular Weight (Da)",
        "Isoelectric Point (pI)",
        "Sequence Length",
    ],
    "Functional / Structural": [
        "Kinase Activity",
        "Zinc-Binding Sites",
        "Metal-Binding Sites",
        "Phosphorylation Sites",
        "Disulfide Bonds",
        "Glycosylation Sites",
        "Signal Peptide",
        "Transmembrane Regions",
        "DNA-Binding Domains",
        "Active Sites",
        "Coiled-Coil Regions",
    ],
    "Biological Classification": [
        "Receptor",
        "Secreted Protein",
        "Cell Adhesion",
        "Transporter / Channel",
        "Enzyme",
        "Transcription Factor",
        "Protease",
        "Cytokine / Growth Factor",
        "Structural Protein",
        "Immune-Related",
    ],
    "Spatial": [
        "Subcellular Localization",
        "Tissue Specificity",
        "Topological Domains",
    ],
    "General Info": [
        "Protein Name",
        "Gene Name",
        "Organism",
        "Protein Function",
    ],
}
ATTRIBUTE_CATEGORIES.update(NEW_CATEGORIES)
for _category, _attrs in NEW_CATEGORIES.items():
    for _attr in _attrs:
        ATTRIBUTE_SOURCES[_attr] = {
            "GO / Domains": "UniProt GO/InterPro/Pfam cross-references and sequence features; domain/family types and coordinates supplemented by InterPro API.",
            "PTM Details": "UniProt registered feature positions, modification descriptions and source evidence. Counts are annotated features, not biological absence.",
            "Membrane / Surface": "UniProt location and topology annotations. Surface candidacy requires cell/plasma membrane location plus extracellular topology or GPI anchor; accessibility remains unverified.",
        }[_category]

# Which attributes are numeric (for histogram) vs categorical (for pie)
NUMERIC_ATTRIBUTES = {
    "Molecular Weight (Da)", "Isoelectric Point (pI)", "Sequence Length",
    "Zinc-Binding Sites", "Metal-Binding Sites", "Phosphorylation Sites",
    "Disulfide Bonds", "Glycosylation Sites", "Transmembrane Regions",
    "DNA-Binding Domains", "Active Sites", "Coiled-Coil Regions",
    "Lipidation Sites",
}
CATEGORICAL_ATTRIBUTES = {
    "Kinase Activity", "Signal Peptide",
    "Receptor", "Secreted Protein", "Cell Adhesion",
    "Transporter / Channel", "Enzyme", "Transcription Factor",
    "Protease", "Cytokine / Growth Factor", "Structural Protein",
    "Immune-Related",
    "Subcellular Localization", "Tissue Specificity",
    "Topological Domains", "Organism",
}
CATEGORICAL_ATTRIBUTES.update(a for attrs in NEW_CATEGORIES.values() for a in attrs if a != "Lipidation Sites")


def parse_entry(entry: dict, selected_attrs: list[str], interpro=None, retrieved_at=None, release=None) -> dict:
    """Parse a single UniProt JSON entry for the selected attributes."""
    result: dict[str, Any] = {}
    acc = entry.get("primaryAccession", "")
    result["Accession"] = acc
    for attr in selected_attrs:
        parser = ATTRIBUTE_PARSERS.get(attr)
        if parser:
            result[attr] = parser(entry)
        else:
            result[attr] = None
    result = add_annotations(entry, selected_attrs, result, interpro, retrieved_at, release)
    # Show the actual matched keywords/names, not every unrelated source keyword.
    records = result["_annotation_records"]
    records[:] = [r for r in records if not (r["Attribute"] in CLASSIFICATION_ATTRIBUTES and r["Method"].startswith("Source "))]
    for attr in selected_attrs:
        if attr not in CLASSIFICATION_ATTRIBUTES or result.get(attr) is not True:
            continue
        parser = ATTRIBUTE_PARSERS[attr]
        for kw in entry.get("keywords", []):
            if parser({"keywords": [kw]}):
                records.append(record(attr, kw.get("name"), method="Matched keyword rule", evidences=kw.get("evidences"), URL=result["UniProt URL"]))
        if parser({"proteinDescription": entry.get("proteinDescription", {})}):
            records.append(record(attr, result["Protein Name"], method="Matched protein-name / EC rule", URL=result["UniProt URL"]))
        if parser({"comments": entry.get("comments", []), "uniProtKBCrossReferences": entry.get("uniProtKBCrossReferences", [])}):
            records.append(record(attr, "Supporting location, catalytic-activity or GO annotation", method="Matched annotation rule", URL=result["UniProt URL"]))
    return result


# ─── Async fetcher ────────────────────────────────────────────────────

import re as _re

# UniProt accession pattern: [OPQ][0-9][A-Z0-9]{3}[0-9] or [A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2}
_ACCESSION_RE = _re.compile(
    r'^[OPQ][0-9][A-Z0-9]{3}[0-9]$|^[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2}$',
    _re.IGNORECASE,
)


def _is_accession(protein_id: str) -> bool:
    """Return True if the ID looks like a UniProt accession (e.g. P60709)."""
    return bool(_ACCESSION_RE.match(protein_id.strip()))


# Supported identifier types (user-facing labels)
ID_TYPES = [
    "Auto-detect",
    "UniProt ID",
    "Gene Name / Symbol",
    "Protein Name",
    "Ensembl ID",
    "RefSeq ID",
]


def _build_query(
    protein_id: str,
    organism_id: str | None = None,
    id_type: str = "Auto-detect",
) -> str:
    """Build a UniProt search query string.

    Supports multiple identifier types:
      Auto-detect  — accession regex → gene name fallback (original logic)
      UniProt ID   — accession:P60709
      Gene Name    — gene_exact:ACTB AND reviewed:true [AND organism_id:…]
      Protein Name — protein_name:"Tumor protein p53" [AND organism_id:…]
      Ensembl ID   — xref:ensembl-ENSG00000141510
      RefSeq ID    — xref:refseq-NP_000537.3
    """
    pid = protein_id.strip()
    if id_type == "Auto-detect":
        if pid.upper().startswith("ENS"):
            id_type = "Ensembl ID"
        elif _re.match(r"^[NX][PMR]_", pid, _re.IGNORECASE):
            id_type = "RefSeq ID"
    # UniProt isoforms need isoform-specific sequence/evidence mapping. Do not
    # reinterpret an isoform as a canonical accession without user review.
    if _re.match(r"^[A-Z0-9]+-\d+$", pid, _re.IGNORECASE):
        return f'accession:"{pid}"'
    escaped = pid.replace("\\", "\\\\").replace('"', '\\"')

    if id_type == "UniProt ID":
        return f"accession:{pid}"

    if id_type == "Gene Name / Symbol":
        query = f'gene_exact:"{escaped}" AND reviewed:true'
        if organism_id:
            query += f" AND organism_id:{organism_id}"
        return query

    if id_type == "Protein Name":
        query = f'protein_name:"{escaped}" AND reviewed:true'
        if organism_id:
            query += f" AND organism_id:{organism_id}"
        return query

    if id_type == "Ensembl ID":
        query = f'xref:ensembl-{escaped}'
        return query + (f" AND organism_id:{organism_id}" if organism_id else "")

    if id_type == "RefSeq ID":
        query = f'xref:refseq-{escaped}'
        return query + (f" AND organism_id:{organism_id}" if organism_id else "")

    # Auto-detect (default) — original logic
    if _is_accession(pid):
        return f"accession:{pid}"
    query = f'gene_exact:"{escaped}" AND reviewed:true'
    if organism_id:
        query += f" AND organism_id:{organism_id}"
    return query


def empty_result(protein_id, selected_attrs, status="Not found"):
    return {"Query ID": protein_id, "Accession": None, "Mapping Status": status,
            "Candidate Count": 0, **{attr: None for attr in selected_attrs},
            "_annotation_records": [], "_candidates": []}


def search_result(data, protein_id, selected_attrs, total=None, release=None):
    """Never silently pick the first of several identifier matches."""
    entries = data.get("results", [])
    count = int(total) if total is not None else len(entries)
    if not entries:
        return empty_result(protein_id, selected_attrs)
    if count > 1:
        result = empty_result(protein_id, selected_attrs, "Needs review")
        result.update({"Candidate Count": count, "_candidates": entries})
        return result
    result = parse_entry(entries[0], selected_attrs, release=release)
    result.update({"Query ID": protein_id, "Mapping Status": "Matched", "Candidate Count": 1})
    return result


async def _fetch_interpro(session, semaphore, accession):
    url = f"https://www.ebi.ac.uk/interpro/api/entry/interpro/protein/uniprot/{accession}/"
    combined = {"results": []}
    # At most 20 pages; never present a partial response as complete.
    try:
        for page in range(20):
            async with semaphore:
                async with session.get(url, params={"page_size": 200} if page == 0 else None,
                                       timeout=aiohttp.ClientTimeout(total=25)) as response:
                    if response.status == 204:
                        return combined, "No registered entries"
                    if response.status != 200:
                        return None, f"Fetch error (HTTP {response.status})"
                    payload = await response.json()
            combined["results"].extend(payload.get("results", []))
            url = payload.get("next")
            if not url:
                return combined, "Retrieved" if combined["results"] else "No registered entries"
            # Only follow the trusted provider's pagination links.
            if not url.startswith("https://www.ebi.ac.uk/interpro/api/"):
                return None, "Fetch error (unexpected pagination URL)"
        return None, "Fetch error (pagination limit)"
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return None, "Fetch error"


async def _fetch_one(session, semaphore, protein_id, selected_attrs,
                     progress_callback=None, organism_id="9606", id_type="Auto-detect"):
    params = {"query": _build_query(protein_id, organism_id, id_type), "format": "json", "size": "25"}
    result = empty_result(protein_id, selected_attrs, "Fetch error")
    try:
        if _re.match(r"^[A-Z0-9]+-\d+$", protein_id, _re.IGNORECASE):
            result = empty_result(protein_id, selected_attrs, "Needs isoform review")
            result["Mapping Note"] = "Isoform-specific mapping is required. Use a canonical accession only if it matches the intended analysis."
            return result
        for attempt in range(MAX_RETRIES):
            try:
                async with semaphore:
                    await asyncio.sleep(INTER_REQUEST_DELAY)
                    async with session.get(BASE_URL, params=params, timeout=aiohttp.ClientTimeout(total=30)) as response:
                        status = response.status
                        if status == 200:
                            data = await response.json()
                            result = search_result(data, protein_id, selected_attrs,
                                                   response.headers.get("X-Total-Results"), response.headers.get("X-UniProt-Release"))
                            break
                        if status in (400, 404):
                            result = empty_result(protein_id, selected_attrs, "Not found" if status == 404 else "Invalid query")
                            break
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(BACKOFF_FACTOR ** (attempt + 1))
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(BACKOFF_FACTOR ** (attempt + 1))
        if result.get("Mapping Status") == "Matched":
            if {"Protein Domains", "Protein Families"}.intersection(selected_attrs):
                payload, domain_status = await _fetch_interpro(session, semaphore, result["Accession"])
                entry = result["_entry"]
                release = result.get("UniProt Release")
                retrieved_at = result.get("Retrieved At")
                result = parse_entry(entry, selected_attrs, interpro=payload, retrieved_at=retrieved_at, release=release)
                result.update({"Query ID": protein_id, "Mapping Status": "Matched", "Candidate Count": 1,
                               "InterPro Status": domain_status})
            else:
                result["InterPro Status"] = "Not requested"
            result["Species Match"] = "Not restricted" if not organism_id else "Selected species" if str(result.get("Taxonomy ID")) == str(organism_id) else "Different species (exact accession)"
        return result
    finally:
        if progress_callback:
            progress_callback()


async def _fetch_batch_async(
    protein_ids: list[str],
    selected_attrs: list[str],
    progress_callback=None,
    organism_id: str | None = "9606",
    id_type: str = "Auto-detect",
) -> list[dict]:
    """Fetch annotations for a batch of protein IDs concurrently."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    # Use ThreadedResolver instead of the default AsyncResolver (aiodns/c-ares)
    # to avoid DNS resolution failures on Windows.
    resolver = aiohttp.resolver.ThreadedResolver()
    connector = aiohttp.TCPConnector(limit=MAX_CONCURRENT, resolver=resolver)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            _fetch_one(session, semaphore, pid.strip(), selected_attrs,
                       progress_callback, organism_id=organism_id,
                       id_type=id_type)
            for pid in dict.fromkeys(pid.strip() for pid in protein_ids if pid.strip())
        ]
        results = await asyncio.gather(*tasks)
    return list(results)


def fetch_batch(
    protein_ids: list[str],
    selected_attrs: list[str],
    progress_callback=None,
    organism_id: str | None = "9606",
    id_type: str = "Auto-detect",
) -> list[dict]:
    """Synchronous wrapper around the async batch fetcher.

    Args:
        protein_ids:  List of UniProt accession or gene symbol strings.
        selected_attrs: List of attribute names to retrieve.
        progress_callback: Optional callable invoked after each protein completes.
        organism_id: NCBI taxonomy ID to restrict gene-name searches.
                     Default '9606' (Homo sapiens). Set to None for any organism.
        id_type: Identifier type — one of ID_TYPES.

    Returns:
        List of dicts, one per protein, containing the selected attributes.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Running inside Streamlit (which has its own loop)
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    _fetch_batch_async(protein_ids, selected_attrs,
                                       progress_callback, organism_id=organism_id,
                                       id_type=id_type),
                )
                return future.result()
        else:
            return loop.run_until_complete(
                _fetch_batch_async(protein_ids, selected_attrs,
                                    progress_callback, organism_id=organism_id,
                                    id_type=id_type)
            )
    except RuntimeError:
        return asyncio.run(
            _fetch_batch_async(protein_ids, selected_attrs,
                               progress_callback, organism_id=organism_id,
                               id_type=id_type)
        )
