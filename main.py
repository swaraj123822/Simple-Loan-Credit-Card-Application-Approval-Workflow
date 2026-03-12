"""
main.py — FastAPI application for the Configurable Workflow Decision Platform.

Endpoint:
    POST /evaluate  →  Evaluate an application request through the stage-based
                        rule engine.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from database import init_db, get_state, upsert_state, insert_audit_log, get_audit_logs
from engine import RuleEngine, ExternalDependencyStage
from external_api import fetch_credit_data, ExternalAPIError
from models import (
    ApplicationRequest,
    AuditLogEntry,
    EvaluationResponse,
    WorkflowStateResponse,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifespan — initialise DB + rule engine once on startup
# ---------------------------------------------------------------------------
rule_engine: RuleEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rule_engine
    init_db()
    rule_engine = RuleEngine("config.json")
    logger.info(
        "Database initialised & rule engine loaded — workflow '%s' v%s (%d stages).",
        rule_engine.workflow_name,
        rule_engine.version,
        len(rule_engine.stages),
    )
    yield


app = FastAPI(
    title="Configurable Workflow Decision Platform",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Retry helper for external dependency
# ---------------------------------------------------------------------------
async def fetch_credit_data_with_retry(
    application_id: str, max_retries: int = 3
) -> dict:
    """Wrap `fetch_credit_data` with up to *max_retries* attempts."""
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            data = await fetch_credit_data(application_id)
            insert_audit_log(
                application_id=application_id,
                action="EXTERNAL_API_CALL",
                result=f"Success on attempt {attempt}",
            )
            return data
        except ExternalAPIError as exc:
            last_error = exc
            insert_audit_log(
                application_id=application_id,
                action="EXTERNAL_API_CALL",
                result=f"Failed attempt {attempt}/{max_retries}: {exc}",
            )
            logger.warning(
                "External API attempt %d/%d failed: %s",
                attempt, max_retries, exc,
            )

    # All retries exhausted
    insert_audit_log(
        application_id=application_id,
        action="EXTERNAL_API_FAILURE",
        result=f"All {max_retries} retries exhausted",
    )
    return None          # signal failure to the engine stage


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@app.post("/evaluate", response_model=EvaluationResponse)
async def evaluate_application(request: ApplicationRequest):
    """
    Process an application through the stage-based rule engine.

    • **Idempotent**: returns cached result if application_id already exists.
    • **Retry**: external dependency stage retried up to the configured count.
    """
    if rule_engine is None:
        raise HTTPException(
            status_code=503,
            detail="Rule engine not initialised. Server may still be starting up.",
        )

    app_id = request.application_id

    # ---- 1. Idempotency check ------------------------------------------
    existing_state = get_state(app_id)
    if existing_state and existing_state["status"] != "pending":
        logger.info("Idempotency hit — returning cached state for %s", app_id)
        audit_trail = get_audit_logs(app_id)
        return EvaluationResponse(
            application_id=app_id,
            decision=existing_state["status"],
            reason="Cached result (idempotent)",
            is_cached=True,
            state=WorkflowStateResponse(**existing_state),
            audit_trail=[AuditLogEntry(**log) for log in audit_trail],
        )

    # ---- 2. Create initial state (pending) -----------------------------
    upsert_state(app_id, "pending")
    insert_audit_log(
        application_id=app_id,
        action="WORKFLOW_STARTED",
        result="Application received; state set to pending",
    )

    # ---- 3. Prepare evaluation data ------------------------------------
    eval_data: dict = {
        "income": request.income,
        "credit_score": request.credit_score,
    }

    # ---- 4. Handle external dependency (if configured) -----------------
    ext_stage = rule_engine.get_external_stage()
    if ext_stage:
        retries = ext_stage.retry_count
        credit_data = await fetch_credit_data_with_retry(app_id, retries)
        if credit_data is not None:
            eval_data["_external_success"] = True
            eval_data.update(credit_data)
            logger.info("Credit data fetched for %s: %s", app_id, credit_data)
        else:
            eval_data["_external_success"] = False
            logger.error("External dependency exhausted for %s", app_id)

    # ---- 5. Run the rule engine ----------------------------------------
    decision, reason = rule_engine.evaluate(app_id, eval_data)

    # ---- 6. Persist final state ----------------------------------------
    final_state = upsert_state(app_id, decision)
    insert_audit_log(
        application_id=app_id,
        action="WORKFLOW_COMPLETED",
        result=f"Final decision: {decision} — {reason}",
    )

    audit_trail = get_audit_logs(app_id)

    return EvaluationResponse(
        application_id=app_id,
        decision=decision,
        reason=reason,
        is_cached=False,
        state=WorkflowStateResponse(**final_state),
        audit_trail=[AuditLogEntry(**log) for log in audit_trail],
    )
