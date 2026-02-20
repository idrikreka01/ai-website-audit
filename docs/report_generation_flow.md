# Report Generation Flow Diagram

## Overview
This diagram shows how audit reports are generated from database data to PDF output.

```mermaid
flowchart TD
    Start([Audit Session Completes]) --> GetSession[Get Session Data<br/>audit_sessions table]
    
    GetSession --> GetResults[Get Audit Results<br/>audit_results table<br/>session_id format: domain__uuid]
    
    GetResults --> GetQuestions[Get All Questions<br/>audit_questions table]
    
    GetQuestions --> MapQuestions[Map Questions by question_id<br/>Create questions_map]
    
    MapQuestions --> GroupByTier[Group Results by Tier<br/>Tier 1, Tier 2, Tier 3]
    
    GroupByTier --> CheckTier1{Tier 1<br/>All Pass?}
    
    CheckTier1 -->|No| Tier1Only[Include Only Tier 1 Questions<br/>Stop here]
    
    CheckTier1 -->|Yes| CheckTier2{Tier 2<br/>All Pass?}
    
    CheckTier2 -->|No| Tier1And2[Include Tier 1 + Tier 2<br/>Stop here]
    
    CheckTier2 -->|Yes| AllTiers[Include Tier 1 + Tier 2 + Tier 3]
    
    Tier1Only --> SortBySeverity[Sort Questions by Severity<br/>Highest to Lowest DESC]
    Tier1And2 --> SortBySeverity
    AllTiers --> SortBySeverity
    
    SortBySeverity --> BuildReport[Build Report Dict<br/>- session_id<br/>- url<br/>- overall_score_percentage<br/>- tier1_passed<br/>- tier2_passed<br/>- tier3_included<br/>- questions array]
    
    BuildReport --> PDFGen{PDF<br/>Generation?}
    
    PDFGen -->|Yes| CreatePDF[Generate PDF Report<br/>- Cover page<br/>- Recommended Changes<br/>- Passed Checks table<br/>- Detailed Results table]
    
    PDFGen -->|No| ReturnJSON[Return JSON Report]
    
    CreatePDF --> SavePDF[Save PDF to<br/>artifacts/reports/{session_id}.pdf]
    
    SavePDF --> ReturnPDF[Return PDF File<br/>via API endpoint]
    
    ReturnJSON --> End([Report Ready])
    ReturnPDF --> End
    
    style Start fill:#e1f5ff
    style End fill:#d4edda
    style CheckTier1 fill:#fff3cd
    style CheckTier2 fill:#fff3cd
    style SortBySeverity fill:#f8d7da
    style BuildReport fill:#d1ecf1
    style CreatePDF fill:#d4edda
```

## Data Flow

### Input Sources
1. **audit_sessions** table
   - `id`, `url`, `overall_score_percentage`, `needs_manual_review`

2. **audit_results** table
   - `question_id`, `session_id` (format: `domain__uuid`), `result` (pass/fail), `reason`, `confidence_score`

3. **audit_questions** table
   - `question_id`, `question`, `category`, `tier` (1-3), `severity` (1-5), `exact_fix`, `page_type`

### Processing Steps

#### Step 1: Data Retrieval
```
session_data = repository.get_session_by_id(session_id)
session_id_str = f"{domain}__{session_id}"
results = repository.get_audit_results_by_session_id(session_id_str)
questions = repository.list_questions()
```

#### Step 2: Question Mapping
```
questions_map = {question_id: question_data}
```

#### Step 3: Tier Grouping
```
tier1_results = [r for r in results if question.tier == 1]
tier2_results = [r for r in results if question.tier == 2]
tier3_results = [r for r in results if question.tier == 3]
```

#### Step 4: Tier Logic
```
if not all(tier1 pass):
    report_questions = tier1_results only
elif not all(tier2 pass):
    report_questions = tier1 + tier2
else:
    report_questions = tier1 + tier2 + tier3
```

#### Step 5: Severity Sorting
```
report_questions.sort(key=lambda x: x["severity"], reverse=True)
```

#### Step 6: Report Building
```python
{
    "session_id": "...",
    "url": "...",
    "overall_score_percentage": 75.5,
    "tier1_passed": True,
    "tier2_passed": True,
    "tier3_included": True,
    "questions": [
        {
            "question_id": 92,
            "question": "...",
            "category": "...",
            "tier": 1,
            "severity": 5,  # Highest first
            "exact_fix": "...",
            "result": "fail",
            "reason": "...",
            "confidence_score": 8
        },
        # ... ordered by severity DESC
    ]
}
```

#### Step 7: PDF Generation (Optional)
- Cover page with overall score
- Recommended Changes section (failed questions with exact_fix)
- Passed Checks table
- Detailed Audit Results table

## API Endpoints

### JSON Report
```
GET /audits/{session_id}/report
→ Returns JSON report data
```

### PDF Report
```
GET /audits/{session_id}/report.pdf
→ Returns PDF file download
```

## Tier Logic Details

```
┌─────────────────────────────────────────┐
│ Tier 1 Questions                        │
│ ✓ All Pass? → Continue                  │
│ ✗ Any Fail? → STOP (Tier 1 only)        │
└─────────────────────────────────────────┘
              ↓ (if all pass)
┌─────────────────────────────────────────┐
│ Tier 2 Questions                        │
│ ✓ All Pass? → Continue                  │
│ ✗ Any Fail? → STOP (Tier 1+2 only)      │
└─────────────────────────────────────────┘
              ↓ (if all pass)
┌─────────────────────────────────────────┐
│ Tier 3 Questions                        │
│ Include all Tier 1 + 2 + 3              │
└─────────────────────────────────────────┘
```

## Severity Ordering

```
Questions sorted by severity (5 → 1):
┌──────────┬──────────┬──────────┐
│ Severity │ Priority │ Example  │
├──────────┼──────────┼──────────┤
│    5     │ Highest  │ Critical │
│    4     │ High     │ Major    │
│    3     │ Medium   │ Moderate │
│    2     │ Low      │ Minor    │
│    1     │ Lowest   │ Trivial  │
└──────────┴──────────┴──────────┘
```

## Example Flow

```
Session: abc123
Tier 1: 5 questions → 4 pass, 1 fail
Tier 2: 3 questions → 2 pass, 1 fail
Tier 3: 2 questions → both pass

Result: Only Tier 1 questions in report
Reason: Tier 1 has failures, so Tier 2/3 excluded
```
