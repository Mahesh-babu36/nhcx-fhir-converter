"""
pipeline/coding_engine.py
--------------------------
Offline clinical coding engine.
Maps diagnosis text → ICD-10 codes.
Maps lab test names → LOINC codes.
No external API calls — works completely offline.
Uses exact → substring → fuzzy matching with confidence scores.
"""

import re
from difflib import SequenceMatcher
from utils import logger


# ── ICD-10 lookup table — 80 most common Indian clinical diagnoses ────────────
ICD10_TABLE = {
    # Cardiovascular
    "acute myocardial infarction": ("I21.9", "Acute myocardial infarction, unspecified"),
    "myocardial infarction": ("I21.9", "Acute myocardial infarction, unspecified"),
    "heart attack": ("I21.9", "Acute myocardial infarction, unspecified"),
    "unstable angina": ("I20.0", "Unstable angina"),
    "angina pectoris": ("I20.9", "Angina pectoris, unspecified"),
    "heart failure": ("I50.9", "Heart failure, unspecified"),
    "congestive heart failure": ("I50.0", "Congestive heart failure"),
    "hypertension": ("I10", "Essential (primary) hypertension"),
    "essential hypertension": ("I10", "Essential (primary) hypertension"),
    "hypertensive heart disease": ("I11.9", "Hypertensive heart disease without heart failure"),
    "atrial fibrillation": ("I48.91", "Unspecified atrial fibrillation"),
    "coronary artery disease": ("I25.10", "Atherosclerotic heart disease of native coronary artery"),
    "stroke": ("I63.9", "Cerebral infarction, unspecified"),
    "cerebrovascular accident": ("I63.9", "Cerebral infarction, unspecified"),
    "cva": ("I63.9", "Cerebral infarction, unspecified"),
    "deep vein thrombosis": ("I82.409", "Acute DVT of unspecified deep veins"),
    "dvt": ("I82.409", "Acute DVT of unspecified deep veins"),
    "pulmonary embolism": ("I26.99", "Other pulmonary embolism without acute cor pulmonale"),

    # Endocrine / Metabolic
    "type 2 diabetes mellitus": ("E11.9", "Type 2 diabetes mellitus without complications"),
    "type 2 diabetes": ("E11.9", "Type 2 diabetes mellitus without complications"),
    "diabetes mellitus": ("E11.9", "Type 2 diabetes mellitus without complications"),
    "diabetes": ("E11.9", "Type 2 diabetes mellitus without complications"),
    "type 1 diabetes": ("E10.9", "Type 1 diabetes mellitus without complications"),
    "diabetic ketoacidosis": ("E11.10", "Type 2 diabetes with ketoacidosis without coma"),
    "hypothyroidism": ("E03.9", "Hypothyroidism, unspecified"),
    "hyperthyroidism": ("E05.90", "Thyrotoxicosis, unspecified without thyrotoxic crisis"),
    "obesity": ("E66.9", "Obesity, unspecified"),
    "dyslipidemia": ("E78.5", "Hyperlipidemia, unspecified"),
    "hyperlipidemia": ("E78.5", "Hyperlipidemia, unspecified"),
    "gout": ("M10.9", "Gout, unspecified"),

    # Respiratory
    "pneumonia": ("J18.9", "Pneumonia, unspecified organism"),
    "community acquired pneumonia": ("J18.9", "Pneumonia, unspecified organism"),
    "cap": ("J18.9", "Pneumonia, unspecified organism"),
    "asthma": ("J45.909", "Unspecified asthma, uncomplicated"),
    "copd": ("J44.1", "Chronic obstructive pulmonary disease with acute exacerbation"),
    "chronic obstructive pulmonary disease": ("J44.1", "COPD with acute exacerbation"),
    "tuberculosis": ("A15.9", "Respiratory tuberculosis, unspecified"),
    "pulmonary tuberculosis": ("A15.9", "Respiratory tuberculosis, unspecified"),
    "tb": ("A15.9", "Respiratory tuberculosis, unspecified"),
    "pleural effusion": ("J90", "Pleural effusion, not elsewhere classified"),
    "covid-19": ("U07.1", "COVID-19, virus identified"),
    "covid": ("U07.1", "COVID-19, virus identified"),

    # Gastrointestinal
    "acute pancreatitis": ("K85.90", "Acute pancreatitis without necrosis or infection, unspecified"),
    "pancreatitis": ("K85.90", "Acute pancreatitis without necrosis or infection, unspecified"),
    "peptic ulcer disease": ("K27.9", "Peptic ulcer, unspecified"),
    "peptic ulcer": ("K27.9", "Peptic ulcer, unspecified"),
    "gastroenteritis": ("K52.9", "Noninfective gastroenteritis and colitis, unspecified"),
    "liver cirrhosis": ("K74.60", "Unspecified cirrhosis of liver"),
    "cirrhosis": ("K74.60", "Unspecified cirrhosis of liver"),
    "hepatitis b": ("B18.1", "Chronic viral hepatitis B without delta-agent"),
    "hepatitis c": ("B18.2", "Chronic viral hepatitis C"),
    "cholecystitis": ("K81.9", "Cholecystitis, unspecified"),
    "appendicitis": ("K37", "Unspecified appendicitis"),
    "intestinal obstruction": ("K56.609", "Unspecified intestinal obstruction, unspecified"),

    # Renal
    "acute kidney injury": ("N17.9", "Acute kidney failure, unspecified"),
    "aki": ("N17.9", "Acute kidney failure, unspecified"),
    "chronic kidney disease": ("N18.9", "Chronic kidney disease, unspecified"),
    "ckd": ("N18.9", "Chronic kidney disease, unspecified"),
    "urinary tract infection": ("N39.0", "Urinary tract infection, site not specified"),
    "uti": ("N39.0", "Urinary tract infection, site not specified"),
    "nephrotic syndrome": ("N04.9", "Nephrotic syndrome with unspecified morphological changes"),
    "kidney stone": ("N20.0", "Calculus of kidney"),
    "renal calculus": ("N20.0", "Calculus of kidney"),

    # Neurological
    "epilepsy": ("G40.909", "Unspecified epilepsy, not intractable, without status epilepticus"),
    "seizure": ("G40.909", "Unspecified epilepsy, not intractable, without status epilepticus"),
    "migraine": ("G43.909", "Migraine, unspecified, not intractable, without status migrainosus"),
    "parkinson disease": ("G20", "Parkinson disease"),
    "parkinsons": ("G20", "Parkinson disease"),
    "meningitis": ("G03.9", "Meningitis, unspecified"),
    "encephalitis": ("G04.90", "Encephalitis, myelitis and encephalomyelitis, unspecified"),

    # Oncology
    "breast cancer": ("C50.911", "Malignant neoplasm of unspecified site of right female breast"),
    "lung cancer": ("C34.90", "Malignant neoplasm of unspecified part of unspecified bronchus and lung"),
    "colon cancer": ("C18.9", "Malignant neoplasm of colon, unspecified"),
    "cervical cancer": ("C53.9", "Malignant neoplasm of cervix uteri, unspecified"),
    "lymphoma": ("C85.90", "Non-Hodgkin lymphoma, unspecified, unspecified site"),

    # Infections
    "sepsis": ("A41.9", "Sepsis, unspecified organism"),
    "dengue fever": ("A90", "Dengue fever [classical dengue]"),
    "dengue": ("A90", "Dengue fever [classical dengue]"),
    "malaria": ("B54", "Unspecified malaria"),
    "typhoid fever": ("A01.00", "Typhoid fever, unspecified"),
    "typhoid": ("A01.00", "Typhoid fever, unspecified"),
    "cellulitis": ("L03.90", "Cellulitis, unspecified"),

    # Musculoskeletal
    "osteoarthritis": ("M19.90", "Unspecified osteoarthritis, unspecified site"),
    "rheumatoid arthritis": ("M06.9", "Rheumatoid arthritis, unspecified"),
    "fracture": ("T14.8XXA", "Other injury of unspecified body region"),
    "osteoporosis": ("M81.0", "Age-related osteoporosis without current pathological fracture"),

    # Mental Health
    "depression": ("F32.9", "Major depressive disorder, single episode, unspecified"),
    "anxiety": ("F41.9", "Anxiety disorder, unspecified"),
    "schizophrenia": ("F20.9", "Schizophrenia, unspecified"),

    # Anaemia
    "anaemia": ("D64.9", "Anemia, unspecified"),
    "anemia": ("D64.9", "Anemia, unspecified"),
    "iron deficiency anaemia": ("D50.9", "Iron deficiency anemia, unspecified"),
    "sickle cell anaemia": ("D57.1", "Sickle-cell disease without crisis"),
}

# ── LOINC lookup table — 60 most common Indian lab tests ─────────────────────
LOINC_TABLE = {
    # Haematology
    "haemoglobin": ("718-7", "Hemoglobin [Mass/volume] in Blood"),
    "hemoglobin": ("718-7", "Hemoglobin [Mass/volume] in Blood"),
    "hb": ("718-7", "Hemoglobin [Mass/volume] in Blood"),
    "hgb": ("718-7", "Hemoglobin [Mass/volume] in Blood"),
    "packed cell volume": ("20570-8", "Hematocrit [Volume Fraction] of Blood"),
    "pcv": ("20570-8", "Hematocrit [Volume Fraction] of Blood"),
    "haematocrit": ("20570-8", "Hematocrit [Volume Fraction] of Blood"),
    "hematocrit": ("20570-8", "Hematocrit [Volume Fraction] of Blood"),
    "total rbc": ("789-8", "Erythrocytes [#/volume] in Blood by Automated count"),
    "red blood cell count": ("789-8", "Erythrocytes [#/volume] in Blood by Automated count"),
    "total wbc": ("6690-2", "Leukocytes [#/volume] in Blood by Automated count"),
    "white blood cell count": ("6690-2", "Leukocytes [#/volume] in Blood by Automated count"),
    "leucocyte count": ("6690-2", "Leukocytes [#/volume] in Blood by Automated count"),
    "total count": ("6690-2", "Leukocytes [#/volume] in Blood by Automated count"),
    "platelet count": ("777-3", "Platelets [#/volume] in Blood by Automated count"),
    "platelets": ("777-3", "Platelets [#/volume] in Blood by Automated count"),
    "plt": ("777-3", "Platelets [#/volume] in Blood by Automated count"),
    "mean corpuscular volume": ("787-2", "MCV [Entitic volume] by Automated count"),
    "mcv": ("787-2", "MCV [Entitic volume] by Automated count"),
    "mch": ("785-6", "MCH [Entitic mass] by Automated count"),
    "mchc": ("786-4", "MCHC [Mass/volume] by Automated count"),
    "neutrophils": ("770-8", "Neutrophils/100 leukocytes in Blood by Automated count"),
    "lymphocytes": ("736-9", "Lymphocytes/100 leukocytes in Blood by Automated count"),
    "eosinophils": ("713-8", "Eosinophils/100 leukocytes in Blood"),
    "monocytes": ("742-7", "Monocytes [#/volume] in Blood by Automated count"),
    "esr": ("30341-2", "Erythrocyte sedimentation rate"),

    # Blood Chemistry
    "blood glucose fasting": ("1558-6", "Fasting glucose [Mass/volume] in Serum or Plasma"),
    "fasting blood sugar": ("1558-6", "Fasting glucose [Mass/volume] in Serum or Plasma"),
    "fbs": ("1558-6", "Fasting glucose [Mass/volume] in Serum or Plasma"),
    "random blood sugar": ("2345-7", "Glucose [Mass/volume] in Serum or Plasma"),
    "rbs": ("2345-7", "Glucose [Mass/volume] in Serum or Plasma"),
    "blood glucose random": ("2345-7", "Glucose [Mass/volume] in Serum or Plasma"),
    "post prandial blood sugar": ("1521-4", "Glucose [Mass/volume] in Serum or Plasma 2 hours post meal"),
    "ppbs": ("1521-4", "Glucose [Mass/volume] in Serum or Plasma 2 hours post meal"),
    "hba1c": ("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood"),
    "glycated haemoglobin": ("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood"),
    "glycosylated hemoglobin": ("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood"),

    # Kidney Function
    "serum creatinine": ("2160-0", "Creatinine [Mass/volume] in Serum or Plasma"),
    "creatinine": ("2160-0", "Creatinine [Mass/volume] in Serum or Plasma"),
    "blood urea nitrogen": ("3094-0", "Urea nitrogen [Mass/volume] in Serum or Plasma"),
    "bun": ("3094-0", "Urea nitrogen [Mass/volume] in Serum or Plasma"),
    "urea": ("3094-0", "Urea nitrogen [Mass/volume] in Serum or Plasma"),
    "uric acid": ("3084-1", "Urate [Mass/volume] in Serum or Plasma"),
    "egfr": ("62238-1", "Glomerular filtration rate/1.73 sq M.predicted [Volume Rate/Area] in Serum, Plasma or Blood"),

    # Liver Function
    "total bilirubin": ("1975-2", "Bilirubin.total [Mass/volume] in Serum or Plasma"),
    "bilirubin": ("1975-2", "Bilirubin.total [Mass/volume] in Serum or Plasma"),
    "direct bilirubin": ("1968-7", "Bilirubin.direct [Mass/volume] in Serum or Plasma"),
    "sgpt": ("1742-6", "Alanine aminotransferase [Enzymatic activity/volume] in Serum or Plasma"),
    "alt": ("1742-6", "Alanine aminotransferase [Enzymatic activity/volume] in Serum or Plasma"),
    "sgot": ("1920-8", "Aspartate aminotransferase [Enzymatic activity/volume] in Serum or Plasma"),
    "ast": ("1920-8", "Aspartate aminotransferase [Enzymatic activity/volume] in Serum or Plasma"),
    "alkaline phosphatase": ("6768-6", "Alkaline phosphatase [Enzymatic activity/volume] in Serum or Plasma"),
    "alp": ("6768-6", "Alkaline phosphatase [Enzymatic activity/volume] in Serum or Plasma"),
    "total protein": ("2885-2", "Protein [Mass/volume] in Serum or Plasma"),
    "albumin": ("1751-7", "Albumin [Mass/volume] in Serum or Plasma"),
    "serum albumin": ("1751-7", "Albumin [Mass/volume] in Serum or Plasma"),

    # Lipid Profile
    "total cholesterol": ("2093-3", "Cholesterol [Mass/volume] in Serum or Plasma"),
    "cholesterol": ("2093-3", "Cholesterol [Mass/volume] in Serum or Plasma"),
    "ldl cholesterol": ("2089-1", "Cholesterol in LDL [Mass/volume] in Serum or Plasma"),
    "ldl": ("2089-1", "Cholesterol in LDL [Mass/volume] in Serum or Plasma"),
    "hdl cholesterol": ("2085-9", "Cholesterol in HDL [Mass/volume] in Serum or Plasma"),
    "hdl": ("2085-9", "Cholesterol in HDL [Mass/volume] in Serum or Plasma"),
    "triglycerides": ("2571-8", "Triglyceride [Mass/volume] in Serum or Plasma"),

    # Cardiac Markers
    "troponin i": ("10839-9", "Troponin I.cardiac [Mass/volume] in Serum or Plasma"),
    "troponin t": ("6597-9", "Troponin T.cardiac [Mass/volume] in Serum or Plasma"),
    "troponin": ("10839-9", "Troponin I.cardiac [Mass/volume] in Serum or Plasma"),
    "cpk mb": ("13969-1", "Creatine kinase.MB [Enzymatic activity/volume] in Serum or Plasma"),
    "ck mb": ("13969-1", "Creatine kinase.MB [Enzymatic activity/volume] in Serum or Plasma"),
    "bnp": ("30934-4", "Natriuretic peptide B [Mass/volume] in Serum or Plasma"),
    "procalcitonin": ("33959-8", "Procalcitonin [Mass/volume] in Serum or Plasma"),
    "crp": ("1988-5", "C reactive protein [Mass/volume] in Serum or Plasma"),
    "c reactive protein": ("1988-5", "C reactive protein [Mass/volume] in Serum or Plasma"),

    # Thyroid
    "tsh": ("3016-3", "Thyrotropin [Units/volume] in Serum or Plasma"),
    "thyroid stimulating hormone": ("3016-3", "Thyrotropin [Units/volume] in Serum or Plasma"),
    "t3": ("3051-0", "Triiodothyronine (T3) [Mass/volume] in Serum or Plasma"),
    "t4": ("3054-4", "Thyroxine (T4) [Mass/volume] in Serum or Plasma"),
    "free t4": ("3024-7", "Thyroxine (T4) free [Mass/volume] in Serum or Plasma"),

    # Electrolytes
    "sodium": ("2951-2", "Sodium [Moles/volume] in Serum or Plasma"),
    "serum sodium": ("2951-2", "Sodium [Moles/volume] in Serum or Plasma"),
    "potassium": ("2823-3", "Potassium [Moles/volume] in Serum or Plasma"),
    "serum potassium": ("2823-3", "Potassium [Moles/volume] in Serum or Plasma"),
    "chloride": ("2075-0", "Chloride [Moles/volume] in Serum or Plasma"),
    "calcium": ("17861-6", "Calcium [Mass/volume] in Serum or Plasma"),
    "serum calcium": ("17861-6", "Calcium [Mass/volume] in Serum or Plasma"),

    # Urine
    "urine routine": ("5767-9", "Appearance of Urine"),
    "urinalysis": ("5767-9", "Appearance of Urine"),
    "urine protein": ("2888-6", "Protein [Mass/volume] in Urine"),
    "urine glucose": ("25428-4", "Glucose [Presence] in Urine by Test strip"),
    "urine creatinine": ("2161-8", "Creatinine [Mass/volume] in Urine"),

    # Coagulation
    "prothrombin time": ("5902-2", "Prothrombin time (PT)"),
    "pt": ("5902-2", "Prothrombin time (PT)"),
    "inr": ("6301-6", "INR in Platelet poor plasma by Coagulation assay"),
    "aptt": ("3173-2", "aPTT in Platelet poor plasma by Coagulation assay"),
    "d dimer": ("48065-7", "Fibrin D-dimer DDU [Mass/volume] in Platelet poor plasma"),
}

FUZZY_THRESHOLD_ICD = 0.60
FUZZY_THRESHOLD_LOINC = 0.65


class ClinicalCodingEngine:
    """
    Offline clinical coding engine.
    No external API — uses embedded lookup tables + fuzzy matching.
    """

    def code_diagnosis(self, diagnosis_text: str) -> dict:
        """Map a diagnosis string to an ICD-10 code."""
        return self._lookup(
            diagnosis_text, ICD10_TABLE,
            system="ICD-10",
            system_uri="http://hl7.org/fhir/sid/icd-10",
            fuzzy_threshold=FUZZY_THRESHOLD_ICD,
        )

    def code_test(self, test_name: str) -> dict:
        """Map a lab test name to a LOINC code."""
        return self._lookup(
            test_name, LOINC_TABLE,
            system="LOINC",
            system_uri="http://loinc.org",
            fuzzy_threshold=FUZZY_THRESHOLD_LOINC,
        )

    def code_all_tests(self, tests: list) -> list:
        """Add LOINC coding to each test in a list."""
        coded = []
        for t in tests:
            if isinstance(t, dict):
                name = t.get("test_name", "")
                t["loinc_coding"] = self.code_test(name)
            coded.append(t)
        return coded

    # ── internal ─────────────────────────────────────────────────────────────
    def _lookup(
        self, raw_text: str, table: dict,
        system: str, system_uri: str, fuzzy_threshold: float
    ) -> dict:
        if not raw_text:
            return self._no_match(system, system_uri)

        needle = raw_text.lower().strip()

        # 1. Exact match
        if needle in table:
            code, display = table[needle]
            return self._match(code, display, system, system_uri, 100, "exact")

        # 2. Substring match — needle inside a key OR key inside needle
        best_sub, best_score = None, 0
        for key, (code, display) in table.items():
            if key in needle or needle in key:
                score = round(
                    SequenceMatcher(None, needle, key).ratio() * 100
                )
                if score > best_score:
                    best_score = score
                    best_sub = (code, display)

        if best_sub and best_score >= 50:
            return self._match(
                best_sub[0], best_sub[1], system, system_uri, best_score, "substring"
            )

        # 3. Fuzzy match
        best_fuzzy, best_fuzzy_score = None, 0
        for key, (code, display) in table.items():
            ratio = SequenceMatcher(None, needle, key).ratio()
            if ratio > best_fuzzy_score:
                best_fuzzy_score = ratio
                best_fuzzy = (code, display)

        if best_fuzzy and best_fuzzy_score >= fuzzy_threshold:
            return self._match(
                best_fuzzy[0], best_fuzzy[1], system, system_uri,
                round(best_fuzzy_score * 100), "fuzzy"
            )

        return self._no_match(system, system_uri)

    def _match(
        self, code, display, system, system_uri, confidence, method
    ) -> dict:
        return {
            "matched": True,
            "code": code,
            "display": display,
            "system": system,
            "system_uri": system_uri,
            "confidence": confidence,
            "match_method": method,
        }

    def _no_match(self, system, system_uri) -> dict:
        return {
            "matched": False,
            "code": None,
            "display": None,
            "system": system,
            "system_uri": system_uri,
            "confidence": 0,
            "match_method": "none",
        }
