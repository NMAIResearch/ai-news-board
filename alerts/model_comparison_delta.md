# AI Regulatory Surveillance: Frontier vs Edge Model Evaluation Delta

**Evaluation Date**: 2026-08-17  
**Benchmark Target**: 20 Sovereign Gazette and Regulatory Items  
**Comparison Entities**: Local Model (`gemma4:12b` via Ollama) vs Frontier Model (`gemini-2.5-pro` / `Gemini Frontier Evaluator`)

---

## 1. Conflict of Interest Declaration (Universal Operating Card Rule 37)

The assisting frontier evaluator (Gemini) and the underlying edge model architecture (`gemma4:12b`) share common architectural provenance within Google / Alphabet. This evaluation is conducted independently under strict statutory definitions. Neither model holds a commercial or institutional bias regarding the evaluated sovereign gazette records.

---

## 2. Quantitative Summary and Agreement Rate (Rule 14)

Across the full dataset of N = 20 gazette records:

| Metric | Numerator | Denominator | Percentage |
|---|---|---|---|
| Total Documents Evaluated (N) | 20 | 20 | 100.0% |
| Operator Duty Shift Agreement (`is_operator_duty_shift`) | 15 | 20 | 75.0% |
| Total Classification Delta (Disagreement) | 5 | 20 | 25.0% |
| Local Model False Positives (Spurious Duty Flags) | 4 | 20 | 20.0% |
| Local Model False Negatives (Missed Enforcement Duties) | 1 | 20 | 5.0% |
| Statutory Citation Grounding (Local Model) | 0 | 20 | 0.0% |
| Statutory Citation Grounding (Gemini Frontier) | 9 | 20 | 45.0% |
| Local Heuristic String Fallback Rate | 7 | 20 | 35.0% |

---

## 3. Qualitative Error Categorisation and Root Causes

### 3.1 Local Model False Positives (Spurious Duty Triggers)
The local model produced four false positive classifications on operator duties due to keyword sensitivity and heuristic fallback defaults:

1. **Unified Agenda of Federal Regulatory and Deregulatory Actions-2026** (`alert_1786938876_9fb3f7`):
   - *Local Model*: Flagged as `is_operator_duty_shift: true` (Duty: `transparency`).
   - *Gemini Finding*: Classified as `is_operator_duty_shift: false`. The Unified Agenda is an administrative forward calendar published under Executive Order 12866. It lists anticipated agency actions but creates zero legal duties for private entities.
2. **Introduction to the Unified Agenda-2026** (`alert_1786938894_af9d57`):
   - *Local Model*: Flagged as `is_operator_duty_shift: true` (Duty: `transparency`).
   - *Gemini Finding*: Classified as `is_operator_duty_shift: false`. This document is an explanatory preface by OIRA detailing publication layout.
3. **Request for Information (RFI) on Modernizing the National Vulnerability Database in the Age of AI** (`alert_1786938961_d00e2a`):
   - *Local Model*: Flagged as `is_operator_duty_shift: true` (Duty: `transparency`).
   - *Gemini Finding*: Classified as `is_operator_duty_shift: false`. An RFI is voluntary information gathering under 15 U.S.C. 272. It establishes no binding compliance requirement.
4. **UK Ofgem / DSIT AI Strategic Approach Request Letters** (`alert_1786939142_4121ad`):
   - *Local Model*: Flagged as `is_operator_duty_shift: true` (Duty: `transparency`).
   - *Gemini Finding*: Classified as `is_operator_duty_shift: false`. The Secretary of State letter directs public statutory regulators (Ofgem, CMA, ICO) to publish strategic plans. It does not directly bind private operators.

### 3.2 Local Model False Negatives (Missed Regulatory Enforcement)
1. **Continuation of National Emergency Regarding Sensitive Technologies and AI in Countries of Concern** (`alert_1786939122_bdbae8`):
   - *Local Model*: Classified as `is_operator_duty_shift: false` (Duty: `none`).
   - *Gemini Finding*: Classified as `is_operator_duty_shift: true` (Duty: `risk_assessment`, Priority 1). This presidential action continues the national emergency under Executive Order 14105, which sustains binding outbound investment notifications and prohibitions under 31 CFR Part 850 for US persons developing or financing advanced AI systems.

---

## 4. Item-by-Item Comparative Delta Matrix

| ID | Title | Local Model Duty | Gemini Duty | Priority (Local / Gem) | Statutory Citation (Gemini) | Delta Reason |
|---|---|---|---|---|---|---|
| `f1324a` | Community Outreach Offices | False | False | P1 / P5 | Null | Agreement; routine administrative notice. |
| `f30ca0` | FDA ISH Pathology Systems | False | False | P1 / P2 | 21 CFR Part 864 | Agreement; medical device reclassification. |
| `9fb3f7` | Unified Agenda 2026 | **True** | **False** | P1 / P2 | EO 12866; 5 U.S.C. 601 | Local False Positive (administrative calendar). |
| `af9d57` | Intro to Unified Agenda | **True** | **False** | P1 / P5 | EO 12866 | Local False Positive (preface text). |
| `3e8a63` | FCC E-Rate Program Review | False | False | P1 / P4 | 47 U.S.C. 254; 47 CFR 54 | Agreement on non-duty; fallback in local. |
| `3a3a04` | Boeing Airworthiness | False | False | P1 / P4 | 14 CFR Part 39 | Agreement; mechanical airframe noise. |
| `a2c711` | CFTC Innovation Advisory Renewal | False | False | P1 / P4 | 5 U.S.C. App. 2 | Agreement; FACA committee charter. |
| `d00e2a` | NIST NVD AI RFI | **True** | **False** | P1 / P2 | 15 U.S.C. 272 | Local False Positive (voluntary consultation). |
| `2fc880` | Polysilicon Import Tariffs | False | False | P1 / P2 | 19 U.S.C. 1862 | Agreement; physical supply chain tariff. |
| `db0138` | CFTC Innovation Advisory Meeting | False | False | P1 / P4 | 5 U.S.C. App. 2 | Agreement; public meeting announcement. |
| `6e9762` | Substance Use Prevention Month | False | False | P1 / P5 | Null | Agreement; ceremonial proclamation. |
| `61ffda` | Export Control Emergency Continuation | False | False | P1 / P2 | 50 U.S.C. 1701; EO 13222 | Agreement; maintains general EAR status quo. |
| `12a8c3` | Vaccine Recommendations | False | False | P1 / P5 | Null | Agreement; healthcare directive. |
| `c6d78d` | Ending Birth Tourism | False | False | P1 / P5 | 8 U.S.C. 1182 | Agreement; immigration policy. |
| `ac9819` | American Citizenship Protection | False | False | P1 / P5 | Null | Agreement; civic policy directive. |
| `c3db57` | National Purple Heart Day | False | False | P1 / P5 | Null | Agreement; ceremonial proclamation. |
| `7266b8` | Colombia Drug Interdiction | False | False | P1 / P5 | 22 U.S.C. 2291-4 | Agreement; foreign assistance finding. |
| `539bb1` | Military Spouse Commission | False | False | P1 / P5 | Null | Agreement; administrative advisory body. |
| `bdbae8` | EO 14105 Sensitive Tech / AI Outbound | **False** | **True** | P1 / P1 | EO 14105; 31 CFR 850 | Local False Negative (missed AI outbound duty). |
| `4121ad` | UK Ofgem / DSIT AI Strategy Letters | **True** | **False** | P2 / P2 | UK AI White Paper CP 815 | Local False Positive (binds regulators, not operators). |

---

## 5. Architectural Recommendations for the Surveillance Daemon

1. **Implement Statutory Negative Filters**:
   - Administrative compendiums (Unified Agenda, Regulatory Plan), voluntary consultations (RFI, RFC), and public hearing notices should be routed to a secondary tracking queue rather than evaluated as primary operator duty shifts.
2. **Priority Score Granularity**:
   - The local daemon default of setting `priority: 1` on unclassified items produces severe alert fatigue. Priority 1 should be reserved strictly for enacted statutes, final binding agency rules, and presidential prohibitions.
3. **Outbound Investment Screening Ruleset**:
   - Incorporate explicit recognition of Treasury outbound technology investment frameworks (EO 14105, 31 CFR Part 850) alongside export controls (EAR / ITAR) to prevent false negatives on capital and technology transfer controls.
