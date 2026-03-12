"""
test_evaluate.py — Verification script for the Workflow Decision Platform.

Tests:
  1. Fresh evaluation         → engine processes and returns a decision
  2. Idempotency              → same application_id returns cached result
  3. Retry / failure handling  → validates audit trail captures retries
  4. Audit logging             → every stage writes entries to the trail
  5. Mandatory check rejection → income <= 0 triggers stage-1 REJECTED
"""

import requests
import json
import sys
import uuid

BASE_URL = "http://127.0.0.1:8000"
ENDPOINT = f"{BASE_URL}/evaluate"

# Unique IDs for each test scenario; Tests 1 & 2 share the same ID for idempotency.
ID_TEST_1_2 = f"TEST-{uuid.uuid4()}"
ID_TEST_4  = f"TEST-{uuid.uuid4()}"
ID_TEST_5  = f"TEST-{uuid.uuid4()}"
ID_TEST_6  = f"TEST-{uuid.uuid4()}"

PASS = "\033[92m✅ PASS\033[0m"
FAIL = "\033[91m❌ FAIL\033[0m"

results: list[tuple[str, bool]] = []


def log(test_name: str, passed: bool, detail: str = ""):
    status = PASS if passed else FAIL
    print(f"  {status}  {test_name}")
    if detail:
        print(f"         ↳ {detail}")
    results.append((test_name, passed))


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# -----------------------------------------------------------------------
# Test 1 — Fresh evaluation (APPROVED path)
# -----------------------------------------------------------------------
def test_fresh_evaluation():
    separator("Test 1: Fresh Evaluation (APPROVED)")
    payload = {
        "application_id": ID_TEST_1_2,
        "income": 80000,
        "credit_score": 780,
    }
    resp = requests.post(ENDPOINT, json=payload)
    data = resp.json()

    log("HTTP 200", resp.status_code == 200, f"Got {resp.status_code}")
    log("Decision is APPROVED", data["decision"] == "APPROVED", f"Got '{data['decision']}'")
    log("is_cached is False", data["is_cached"] is False, f"Got {data['is_cached']}")
    log("State status matches decision",
        data["state"]["status"] == "APPROVED",
        f"State status: '{data['state']['status']}'")
    log("Audit trail is non-empty",
        len(data["audit_trail"]) > 0,
        f"{len(data['audit_trail'])} entries")

    return data


# -----------------------------------------------------------------------
# Test 2 — Idempotency (same application_id)
# -----------------------------------------------------------------------
def test_idempotency():
    separator("Test 2: Idempotency Check")
    payload = {
        "application_id": ID_TEST_1_2,    # same as Test 1
        "income": 80000,
        "credit_score": 780,
    }
    resp = requests.post(ENDPOINT, json=payload)
    data = resp.json()

    log("HTTP 200", resp.status_code == 200)
    log("is_cached is True", data["is_cached"] is True, f"Got {data['is_cached']}")
    log("Decision is still APPROVED",
        data["decision"] == "APPROVED",
        f"Got '{data['decision']}'")
    log("Reason indicates caching",
        "Cached" in data.get("reason", "") or "idempotent" in data.get("reason", ""),
        f"Reason: '{data['reason']}'")


# -----------------------------------------------------------------------
# Test 3 — Audit log completeness
# -----------------------------------------------------------------------
def test_audit_logging(first_result: dict):
    separator("Test 3: Audit Log Completeness")
    trail = first_result["audit_trail"]
    actions = [entry["action"] for entry in trail]

    log("WORKFLOW_STARTED logged",
        "WORKFLOW_STARTED" in actions)
    log("ENGINE_START logged",
        "ENGINE_START" in actions)
    log("Stage evaluations logged",
        any("STAGE_" in a and "EVALUATED" in a for a in actions),
        f"Actions: {actions}")
    log("DECISION_REACHED logged",
        "DECISION_REACHED" in actions)
    log("WORKFLOW_COMPLETED logged",
        "WORKFLOW_COMPLETED" in actions)

    # Check that external API call was recorded
    external_actions = [a for a in actions if "EXTERNAL_API" in a]
    log("External API call(s) logged",
        len(external_actions) > 0,
        f"Found {len(external_actions)} external API log(s)")

    # Check for retry evidence in the audit trail entries
    retry_entries = [
        e for e in trail
        if "EXTERNAL_API_CALL" in e["action"]
    ]
    if retry_entries:
        last_attempt = retry_entries[-1]["result"]
        log("Retry attempts visible in audit",
            "attempt" in last_attempt.lower(),
            f"Last entry: '{last_attempt}'")


# -----------------------------------------------------------------------
# Test 4 — MANUAL_REVIEW path
# -----------------------------------------------------------------------
def test_manual_review():
    separator("Test 4: MANUAL_REVIEW Path (score 650)")
    payload = {
        "application_id": ID_TEST_4,
        "income": 55000,
        "credit_score": 650,
    }
    resp = requests.post(ENDPOINT, json=payload)
    data = resp.json()

    log("HTTP 200", resp.status_code == 200)
    log("Decision is MANUAL_REVIEW",
        data["decision"] == "MANUAL_REVIEW",
        f"Got '{data['decision']}'")


# -----------------------------------------------------------------------
# Test 5 — REJECTED via mandatory check (income <= 0)
# -----------------------------------------------------------------------
def test_mandatory_rejection():
    separator("Test 5: Mandatory Check Rejection (income=0)")
    payload = {
        "application_id": ID_TEST_5,
        "income": 0,
        "credit_score": 800,
    }
    resp = requests.post(ENDPOINT, json=payload)
    data = resp.json()

    log("HTTP 200", resp.status_code == 200)
    log("Decision is REJECTED",
        data["decision"] == "REJECTED",
        f"Got '{data['decision']}'")
    log("Rejected at stage 1 (mandatory check)",
        "Mandatory check FAILED" in data.get("reason", ""),
        f"Reason: '{data['reason']}'")


# -----------------------------------------------------------------------
# Test 6 — REJECTED via low credit score
# -----------------------------------------------------------------------
def test_low_credit_rejection():
    separator("Test 6: Rejection via Low Credit Score (score=450)")
    payload = {
        "application_id": ID_TEST_6,
        "income": 40000,
        "credit_score": 450,
    }
    resp = requests.post(ENDPOINT, json=payload)
    data = resp.json()

    log("HTTP 200", resp.status_code == 200)
    log("Decision is REJECTED",
        data["decision"] == "REJECTED",
        f"Got '{data['decision']}'")
    log("Reason mentions credit_score < 600",
        "credit_score" in data.get("reason", "").lower() and "< 600" in data.get("reason", ""),
        f"Reason: '{data['reason']}'")


# -----------------------------------------------------------------------
# Run all tests
# -----------------------------------------------------------------------
if __name__ == "__main__":
    print("\n" + "🔬 " * 20)
    print("  WORKFLOW DECISION PLATFORM — TEST SUITE")
    print("🔬 " * 20)

    try:
        first = test_fresh_evaluation()
        test_idempotency()
        test_audit_logging(first)
        test_manual_review()
        test_mandatory_rejection()
        test_low_credit_rejection()
    except requests.ConnectionError:
        print(f"\n{FAIL}  Could not connect to {BASE_URL}")
        print("         Make sure the server is running:")
        print("         python -m uvicorn main:app --port 8000")
        sys.exit(1)

    # Summary
    total = len(results)
    passed = sum(1 for _, p in results if p)
    failed = total - passed

    separator("SUMMARY")
    print(f"  Total : {total}")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")

    if failed:
        print(f"\n  ⚠️  {failed} test(s) failed!")
        sys.exit(1)
    else:
        print(f"\n  🎉 All {total} tests passed!")
        sys.exit(0)
