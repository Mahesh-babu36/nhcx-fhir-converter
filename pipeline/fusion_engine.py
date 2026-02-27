"""
pipeline/fusion_engine.py
--------------------------
Merges clinical data from multiple PDF documents into one unified record.
Detects conflicts when the same field has different values across documents.
Resolves conflicts using a document authority hierarchy.
Tracks provenance — which document each field came from.
"""

from utils import logger


# Authority hierarchy: higher number = more authoritative for that field
FIELD_AUTHORITY = {
    # Patient demographics — discharge summary is most authoritative
    "patient_name":       {"discharge_summary": 3, "diagnostic_report": 2, "prescription": 1},
    "patient_age":        {"discharge_summary": 3, "diagnostic_report": 2, "prescription": 1},
    "patient_gender":     {"discharge_summary": 3, "diagnostic_report": 2, "prescription": 1},
    "patient_id":         {"discharge_summary": 3, "diagnostic_report": 2, "prescription": 1},
    "hospital_name":      {"discharge_summary": 3, "diagnostic_report": 2, "prescription": 2},
    "treating_doctor":    {"discharge_summary": 3, "prescription": 2, "diagnostic_report": 1},

    # Clinical data — discharge summary wins
    "primary_diagnosis":  {"discharge_summary": 3, "diagnostic_report": 1, "prescription": 1},
    "admission_date":     {"discharge_summary": 3, "diagnostic_report": 1},
    "discharge_date":     {"discharge_summary": 3},
    "condition_at_discharge": {"discharge_summary": 3},
    "medications_at_discharge": {"discharge_summary": 3, "prescription": 2},
    "procedures_performed": {"discharge_summary": 3, "diagnostic_report": 1},

    # Lab results — diagnostic report is authoritative
    "tests":              {"diagnostic_report": 3, "discharge_summary": 1},

    # Insurance — all equally authoritative
    "insurer_name":       {"discharge_summary": 2, "diagnostic_report": 2},
    "insurance_id":       {"discharge_summary": 2, "diagnostic_report": 2},
}

# Fields that should be merged (lists combined) rather than one winning
MERGE_AS_LIST = {"tests", "secondary_diagnoses", "procedures_performed"}

# Fields where small differences are acceptable (age ±2, dates ±3 days)
NUMERIC_TOLERANCE = {"patient_age": 2}


class DocumentFusionEngine:
    """
    Fuses multiple processed documents into one unified clinical record.
    """

    def fuse(self, processed_docs: list) -> dict:
        """
        Args:
            processed_docs: list of dicts, each having:
                file_name, doc_type, clinical_data

        Returns:
            dict with keys:
                unified_record  – merged clinical data dict
                conflicts       – list of detected conflicts
                provenance      – {field: source_file} mapping
                sources         – list of source file names
        """
        if not processed_docs:
            return self._empty()

        if len(processed_docs) == 1:
            d = processed_docs[0]
            return {
                "unified_record": d.get("clinical_data", {}),
                "conflicts": [],
                "provenance": {
                    k: d.get("file_name", "unknown")
                    for k in d.get("clinical_data", {})
                },
                "sources": [d.get("file_name", "unknown")],
            }

        unified = {}
        provenance = {}
        conflicts = []

        all_fields = set()
        for doc in processed_docs:
            all_fields.update(doc.get("clinical_data", {}).keys())

        for field in all_fields:
            values_by_doc = {}
            for doc in processed_docs:
                val = doc.get("clinical_data", {}).get(field)
                if val is not None and val != "" and val != []:
                    values_by_doc[doc.get("doc_type", "unknown")] = (
                        val, doc.get("file_name", "unknown")
                    )

            if not values_by_doc:
                continue

            if len(values_by_doc) == 1:
                # Only one document has this field — use it directly
                doc_type, (val, fname) = next(iter(values_by_doc.items()))
                unified[field] = val
                provenance[field] = fname
                continue

            # Multiple documents have this field — check for conflict
            if field in MERGE_AS_LIST:
                # Merge all list values, deduplicate
                merged = []
                seen = set()
                for doc_type, (val, fname) in values_by_doc.items():
                    items = val if isinstance(val, list) else [val]
                    for item in items:
                        key = str(item).lower()[:50]
                        if key not in seen:
                            merged.append(item)
                            seen.add(key)
                unified[field] = merged
                provenance[field] = "merged from multiple documents"
                continue

            # Check if values are effectively the same
            raw_values = [str(v).strip().lower() for (v, _) in values_by_doc.values()]
            if len(set(raw_values)) == 1:
                # All agree
                best_doc = self._pick_authority(field, values_by_doc)
                val, fname = values_by_doc[best_doc]
                unified[field] = val
                provenance[field] = fname
                continue

            # Real conflict detected
            conflict_entries = [
                {"document": fname, "doc_type": dt, "value": str(v)}
                for dt, (v, fname) in values_by_doc.items()
            ]

            best_doc = self._pick_authority(field, values_by_doc)
            resolved_val, resolved_fname = values_by_doc[best_doc]

            conflict = {
                "field": field,
                "values": conflict_entries,
                "resolved_to": str(resolved_val),
                "resolved_from": resolved_fname,
                "resolution": f"Used {best_doc} (highest authority for this field)",
            }
            conflicts.append(conflict)
            logger.warning(f"Conflict on '{field}': resolved to '{resolved_val}' from {resolved_fname}")

            unified[field] = resolved_val
            provenance[field] = resolved_fname

        logger.info(
            f"Fusion complete — {len(processed_docs)} docs, "
            f"{len(unified)} fields, {len(conflicts)} conflicts"
        )

        return {
            "unified_record": unified,
            "conflicts": conflicts,
            "provenance": provenance,
            "sources": [d.get("file_name", "unknown") for d in processed_docs],
        }

    def _pick_authority(self, field: str, values_by_doc: dict) -> str:
        """Return the doc_type with the highest authority for this field."""
        authority_map = FIELD_AUTHORITY.get(field, {})
        if not authority_map:
            return next(iter(values_by_doc))

        best = max(
            values_by_doc.keys(),
            key=lambda dt: authority_map.get(dt, 0)
        )
        return best

    def _empty(self) -> dict:
        return {
            "unified_record": {},
            "conflicts": [],
            "provenance": {},
            "sources": [],
        }
