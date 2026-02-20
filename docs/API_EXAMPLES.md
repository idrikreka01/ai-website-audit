# API Examples

## Complete Workflow Example

### 1. Create Audit Session

```bash
curl -X POST http://localhost:8000/audits \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example-shop.com",
    "mode": "standard"
  }'
```

**Response**:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "url": "https://example-shop.com",
  "status": "queued",
  "created_at": "2026-02-20T10:00:00Z"
}
```

### 2. Poll for Completion

```bash
# Wait a few minutes, then check status
curl http://localhost:8000/audits/550e8400-e29b-41d4-a716-446655440000
```

**Response** (when completed):
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "url": "https://example-shop.com",
  "status": "completed",
  "page_coverage_score": 4,
  "ai_audit_score": 0.85,
  "ai_audit_flag": "high",
  "functional_flow_score": 3,
  "overall_score_percentage": 87.5,
  "needs_manual_review": false,
  "pages": [
    {
      "id": "...",
      "page_type": "homepage",
      "viewport": "desktop",
      "status": "ok"
    }
  ]
}
```

### 3. Get Report

```bash
curl http://localhost:8000/audits/550e8400-e29b-41d4-a716-446655440000/report
```

**Response**:
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "url": "https://example-shop.com",
  "overall_score_percentage": 87.5,
  "overall_score": 87.5,
  "stage_scores": {
    "awareness": 90.0,
    "consideration": 85.0,
    "conversion": 88.0
  },
  "category_scores": [
    {
      "category": "Navigation",
      "score": 95.0,
      "total_questions": 5,
      "total_weight": 45.0
    }
  ],
  "questions": [
    {
      "question_id": 1,
      "question": "Is there a clear return policy link?",
      "category": "Awareness",
      "tier": 1,
      "severity": 5,
      "result": "pass",
      "reason": "Return policy link found in footer",
      "confidence_score": 9
    }
  ],
  "stage_summaries": [
    {
      "stage": "Awareness",
      "summary": "The homepage effectively communicates...",
      "generated_at": "2026-02-20T10:05:00Z"
    }
  ],
  "storefront_report_card": {
    "stage_descriptions": {
      "awareness": "Strong homepage messaging...",
      "consideration": "Product pages provide...",
      "conversion": "Checkout flow is streamlined..."
    },
    "final_thoughts": "Overall, the website demonstrates..."
  },
  "actionable_findings": []
}
```

### 4. Get Results

```bash
curl http://localhost:8000/audits/550e8400-e29b-41d4-a716-446655440000/results
```

**Response**:
```json
[
  {
    "result_id": 1,
    "question_id": 1,
    "session_id": "example-shop.com__550e8400-e29b-41d4-a716-446655440000",
    "result": "pass",
    "reason": "Clear evidence of return policy link in footer",
    "confidence_score": 9
  },
  {
    "result_id": 2,
    "question_id": 2,
    "session_id": "example-shop.com__550e8400-e29b-41d4-a716-446655440000",
    "result": "unknown",
    "reason": "Insufficient evidence to determine if privacy policy is accessible",
    "confidence_score": 5
  }
]
```

### 5. Get Artifacts

```bash
curl http://localhost:8000/audits/550e8400-e29b-41d4-a716-446655440000/artifacts
```

**Response**:
```json
[
  {
    "id": "...",
    "type": "screenshot",
    "storage_uri": "artifacts/example-shop.com__550e8400/.../screenshot.png",
    "size_bytes": 123456,
    "created_at": "2026-02-20T10:01:00Z"
  }
]
```

## Question Management

### List Questions

```bash
# All questions
curl http://localhost:8000/audits/questions

# Filter by stage
curl http://localhost:8000/audits/questions?stage=Awareness

# Filter by page type
curl http://localhost:8000/audits/questions?page_type=homepage

# Combined filters
curl http://localhost:8000/audits/questions?stage=Awareness&page_type=homepage
```

### Get Question

```bash
curl http://localhost:8000/audits/questions/1
```

### Get Question Results

```bash
curl http://localhost:8000/audits/questions/1/results
```

### Create Question

```bash
curl -X POST http://localhost:8000/audits/questions \
  -H "Content-Type: application/json" \
  -d '{
    "category": "Awareness",
    "question": "Is there a clear return policy link?",
    "ai_criteria": "Look for return policy link in footer or navigation",
    "tier": 1,
    "severity": 5,
    "bar_chart_category": "Trust & Policies",
    "exact_fix": "Add a clear \"Returns\" link in the footer",
    "page_type": "homepage"
  }'
```

### Update Question

```bash
curl -X PUT http://localhost:8000/audits/questions/1 \
  -H "Content-Type: application/json" \
  -d '{
    "severity": 4
  }'
```

### Delete Question

```bash
curl -X DELETE http://localhost:8000/audits/questions/1
```

## Error Handling

### Invalid URL
```json
{
  "detail": "Invalid URL: Scheme must be http or https"
}
```

### Session Not Found
```json
{
  "detail": "Audit session {session_id} not found"
}
```

### Job Enqueue Failed
```json
{
  "detail": "Failed to enqueue audit job. Please try again later."
}
```

## Python Client Example

```python
import requests

BASE_URL = "http://localhost:8000"

# Create audit
response = requests.post(
    f"{BASE_URL}/audits",
    json={"url": "https://example-shop.com", "mode": "standard"}
)
session_id = response.json()["id"]

# Poll for completion
import time
while True:
    response = requests.get(f"{BASE_URL}/audits/{session_id}")
    data = response.json()
    if data["status"] in ["completed", "partial", "failed"]:
        break
    time.sleep(5)

# Get report
response = requests.get(f"{BASE_URL}/audits/{session_id}/report")
report = response.json()

print(f"Overall Score: {report['overall_score_percentage']}%")
print(f"Stage Scores: {report['stage_scores']}")
```

## JavaScript Client Example

```javascript
const BASE_URL = 'http://localhost:8000';

// Create audit
const createResponse = await fetch(`${BASE_URL}/audits`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    url: 'https://example-shop.com',
    mode: 'standard'
  })
});
const { id: sessionId } = await createResponse.json();

// Poll for completion
const pollStatus = async () => {
  const response = await fetch(`${BASE_URL}/audits/${sessionId}`);
  const data = await response.json();
  return data.status;
};

let status = 'queued';
while (['queued', 'running'].includes(status)) {
  await new Promise(resolve => setTimeout(resolve, 5000));
  status = await pollStatus();
}

// Get report
const reportResponse = await fetch(`${BASE_URL}/audits/${sessionId}/report`);
const report = await reportResponse.json();

console.log(`Overall Score: ${report.overall_score_percentage}%`);
console.log(`Stage Scores:`, report.stage_scores);
```
