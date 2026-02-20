# Implementation Plan: Add UNKNOWN Status Support

## Goal
Change audit evaluation output from `PASS | FAIL` only to `pass | fail | unknown`, with logic: "if unclear → UNKNOWN, not FAIL".

## Context
Current system forces PASS/FAIL even when evidence is insufficient. Memo requires UNKNOWN to avoid false FAILs. Quality priority: false FAIL is worst outcome; UNKNOWN is acceptable when evidence insufficient.

---

## Files to Modify

### 1. `audit_evaluator.py` — JSON Schema & Prompt Instructions

**Location:** `audit_evaluator.py`, method `build_request()` around line 308-346

**Changes:**

**A. Update system instruction prompt:**
- **Remove:** "Allowed outputs: PASS or FAIL ONLY. Do not return UNKNOWN. Return PASS/FAIL only."
- **Remove:** "If evidence is missing, inconclusive, or unclear, return FAIL."
- **Add:** "Allowed outputs: PASS, FAIL, or UNKNOWN."
- **Add:** "Confidence gating rule: FAIL requires confidence >= 8 AND clear evidence pointer. If evidence is missing, inconclusive, unclear, or confidence < 8, return UNKNOWN instead of FAIL."
- **Update step 6:** "Return PASS only if criteria are clearly met on both devices. Return FAIL only if criteria are clearly NOT met AND you have high confidence (>=8) AND clear evidence. Return UNKNOWN if evidence is insufficient, unclear, conflicting, or confidence is low (<8)."

**B. Update JSON schema enum:**
- **Change:** `"pass_fail": {"type": "string", "enum": ["PASS", "FAIL"]}`
- **To:** `"pass_fail": {"type": "string", "enum": ["PASS", "FAIL", "UNKNOWN"]}`

**C. Update confidence guidance:**
- **Add:** "When assigning confidence_score_1_to_10: If confidence < 8, you MUST return UNKNOWN, not FAIL. Only return FAIL when confidence >= 8 AND evidence clearly shows failure."

---

### 2. `api/schemas.py` — API Request/Response Schemas

**Location:** `api/schemas.py`, multiple classes

**Changes:**

**A. `AuditResultResponse` (around line 157):**
- **Change:** `result: Literal["pass", "fail"]`
- **To:** `result: Literal["pass", "fail", "unknown"]`

**B. `CreateAuditResultRequest` (around line 169):**
- **Change:** `result: Literal["pass", "fail"]`
- **To:** `result: Literal["pass", "fail", "unknown"]`
- **Update description:** `"Result: pass, fail, or unknown"`

**C. `AuditReportQuestionResponse` (around line 184):**
- **Change:** `result: Literal["pass", "fail"]`
- **To:** `result: Literal["pass", "fail", "unknown"]`

**D. Any other `Literal["pass", "fail"]` occurrences:**
- Search file for all `Literal["pass", "fail"]` and update to include `"unknown"`

---

### 3. `worker/orchestrator.py` — Result Processing Logic

**Location:** `worker/orchestrator.py`, method `compute_ai_audit_score()` around line 26-80

**Changes:**

**A. Handle UNKNOWN in score calculation:**
- **Current:** `passed = result_value == "PASS"`
- **Update logic:** UNKNOWN should be treated as "neither pass nor fail" — exclude from weighted score OR count as 0.5 weight (your choice, document decision).
- **Example approach:**
  ```python
  result_value = result.get("result", "").upper()
  if result_value == "PASS":
      passed = True
  elif result_value == "FAIL":
      passed = False
  elif result_value == "UNKNOWN":
      # Option 1: Skip (don't count in score)
      continue
      # Option 2: Count as neutral (0.5 weight)
      # passed = None  # handle separately
  ```

**B. Logging:**
- Update logs to include UNKNOWN counts separately from PASS/FAIL.

---

### 4. `worker/report_generator.py` — Report Rendering

**Location:** `worker/report_generator.py`, check where `result == "fail"` is used

**Changes:**

**A. Report display logic:**
- **Current:** Reports show Pass/Fail only.
- **Update:** Add UNKNOWN display option (e.g., gray/neutral styling, "Unclear" label, or exclude from report with note).
- **Decision needed:** Should UNKNOWN appear in report? Memo says user-facing is "Pass, Fail, or Fix only" — but Fix is for FAIL. Decide: show UNKNOWN or hide it with note.

**B. Failed questions filter:**
- **Current:** `failed_questions = [q for q in questions if q.get("result") == "fail"]`
- **Update:** Decide if UNKNOWN should be included in "failed" section or separate section.

---

### 5. Database Schema (if needed)

**Check:** `shared/repository.py` and DB migrations

**Changes:**

**A. Check `audit_results` table:**
- If `result` column is enum or check constraint, add `"unknown"` to allowed values.
- If migration needed, create: `migrations/versions/XXXX_add_unknown_status_to_audit_results.py`

**B. Repository methods:**
- Check `create_audit_result()` and `update_audit_result()` — ensure they accept `"unknown"`.
- Update any validation that rejects non-pass/fail values.

---

### 6. `audit_evaluator.py` — Response Parsing

**Location:** `audit_evaluator.py`, wherever response is parsed

**Changes:**

**A. Normalize result values:**
- **Current:** May normalize to lowercase `"pass"` / `"fail"`.
- **Update:** Normalize `"UNKNOWN"` → `"unknown"` (or keep uppercase, be consistent).

**B. Validation:**
- Update any validation that rejects UNKNOWN to accept it.

---

### 7. `worker/html_analysis.py` (if used for evaluation)

**Location:** `worker/html_analysis.py`, check if it has similar PASS/FAIL logic

**Changes:**

- If this file also evaluates questions, apply same changes as `audit_evaluator.py` (prompt + schema).

---

## Implementation Steps

1. **Update JSON schema** in `audit_evaluator.py` (add UNKNOWN to enum).
2. **Update prompt instructions** in `audit_evaluator.py` (remove "FAIL only", add confidence gating rule).
3. **Update API schemas** in `api/schemas.py` (all `Literal["pass", "fail"]` → include `"unknown"`).
4. **Update score calculation** in `worker/orchestrator.py` (handle UNKNOWN in weighted score).
5. **Update report rendering** in `worker/report_generator.py` (decide how to display UNKNOWN).
6. **Check DB schema** — add `"unknown"` to enum/constraint if needed.
7. **Test:** Run evaluation on a site with unclear evidence — verify UNKNOWN is returned when confidence < 8 or evidence insufficient.
8. **Update any validation** that rejects non-pass/fail values.

---

## Testing Checklist

- [ ] LLM returns UNKNOWN when confidence < 8
- [ ] LLM returns UNKNOWN when evidence is missing/unclear
- [ ] LLM still returns PASS when criteria clearly met
- [ ] LLM still returns FAIL when criteria clearly NOT met AND confidence >= 8
- [ ] API accepts `result: "unknown"` in requests
- [ ] API returns `result: "unknown"` in responses
- [ ] Score calculation handles UNKNOWN correctly
- [ ] Report displays/handles UNKNOWN appropriately
- [ ] DB stores `"unknown"` without errors
- [ ] No validation errors when UNKNOWN is used

---

## Notes

- **Confidence threshold:** Memo suggests confidence >= 0.8 (8/10) for FAIL. Adjust if needed.
- **Report display:** Decide whether UNKNOWN appears in user-facing report or is hidden with note.
- **Score calculation:** Document decision on how UNKNOWN affects overall score (skip vs neutral weight).
