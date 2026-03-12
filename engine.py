"""
engine.py — OOP-based Stage-driven Rule Engine.

Loads config.json, evaluates stages sequentially with conditional branching,
handles external dependency stages, and writes every step to the AuditLog.
"""

import json
import operator
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from database import insert_audit_log

# ---------------------------------------------------------------------------
# Operator look-up
# ---------------------------------------------------------------------------
OPERATOR_MAP: dict[str, Any] = {
    ">=": operator.ge,
    "<=": operator.le,
    ">":  operator.gt,
    "<":  operator.lt,
    "==": operator.eq,
    "!=": operator.ne,
}


# ---------------------------------------------------------------------------
# Abstract base stage
# ---------------------------------------------------------------------------
class Stage(ABC):
    """Base class for all workflow stages."""

    def __init__(self, stage_id: str, stage_type: str):
        self.stage_id = stage_id
        self.stage_type = stage_type

    @abstractmethod
    def evaluate(self, data: dict) -> tuple[str, str]:
        """
        Evaluate the stage against the supplied data.

        Returns
        -------
        (outcome, detail)
            outcome: "next" to continue, or a terminal decision
                     like "APPROVED", "REJECTED", "MANUAL_REVIEW", "SYSTEM_FAILURE"
            detail:  human-readable explanation
        """
        ...


# ---------------------------------------------------------------------------
# Stage: mandatory_check  (e.g. "income > 0")
# ---------------------------------------------------------------------------
class MandatoryCheckStage(Stage):
    """Evaluates a simple expression rule like 'income > 0'."""

    def __init__(self, stage_id: str, rule_expr: str,
                 on_success: str, on_failure: str):
        super().__init__(stage_id, "mandatory_check")
        self.rule_expr = rule_expr
        self.on_success = on_success
        self.on_failure = on_failure
        self._field, self._op_symbol, self._threshold = self._parse(rule_expr)
        self._compare = OPERATOR_MAP[self._op_symbol]

    @staticmethod
    def _parse(expr: str) -> tuple[str, str, float]:
        """Parse a rule string like 'income > 0' into (field, op, value)."""
        parts = expr.split()
        if len(parts) != 3:
            raise ValueError(f"Cannot parse rule expression: {expr!r}")
        field, op, value = parts
        return field, op, float(value)

    def evaluate(self, data: dict) -> tuple[str, str]:
        value = data.get(self._field)
        if value is None:
            return self.on_failure, f"Field '{self._field}' missing from data"

        passed = self._compare(value, self._threshold)
        if passed:
            return self.on_success, (
                f"Mandatory check PASSED: {self._field}={value} "
                f"{self._op_symbol} {self._threshold}"
            )
        return self.on_failure, (
            f"Mandatory check FAILED: {self._field}={value} "
            f"does not satisfy {self._op_symbol} {self._threshold}"
        )


# ---------------------------------------------------------------------------
# Stage: external_dependency  (e.g. fetch_credit_data)
# ---------------------------------------------------------------------------
class ExternalDependencyStage(Stage):
    """Represents an external API call stage. Actual call is delegated to the
    caller (main.py) — this stage just records the outcome."""

    def __init__(self, stage_id: str, action: str,
                 retry_count: int, on_success: str, on_failure: str):
        super().__init__(stage_id, "external_dependency")
        self.action = action
        self.retry_count = retry_count
        self.on_success = on_success
        self.on_failure = on_failure

    def evaluate(self, data: dict) -> tuple[str, str]:
        """
        Check whether the external data was successfully fetched.
        The caller sets data["_external_success"] before invoking this.
        """
        if data.get("_external_success"):
            return self.on_success, f"External action '{self.action}' succeeded"
        return self.on_failure, f"External action '{self.action}' failed after retries"


# ---------------------------------------------------------------------------
# Stage: threshold_check  (branching on a numeric variable)
# ---------------------------------------------------------------------------
class ThresholdCheckStage(Stage):
    """Evaluates a variable against ordered branches (>=, between, <, etc.)."""

    def __init__(self, stage_id: str, variable: str, branches: list[dict]):
        super().__init__(stage_id, "threshold_check")
        self.variable = variable
        self.branches = branches

    def evaluate(self, data: dict) -> tuple[str, str]:
        value = data.get(self.variable)
        if value is None:
            return "REJECTED", f"Variable '{self.variable}' missing from data"

        for branch in self.branches:
            condition = branch["condition"]
            result = branch["result"]

            if condition == "between":
                lo, hi = branch["min"], branch["max"]
                if lo <= value <= hi:
                    return result, (
                        f"{self.variable}={value} is between {lo} and {hi}"
                    )
            elif condition in OPERATOR_MAP:
                threshold = branch["value"]
                if OPERATOR_MAP[condition](value, threshold):
                    return result, (
                        f"{self.variable}={value} {condition} {threshold}"
                    )

        return "REJECTED", f"No branch matched for {self.variable}={value}"


# ---------------------------------------------------------------------------
# Stage factory
# ---------------------------------------------------------------------------
def _build_stage(cfg: dict) -> Stage:
    """Instantiate the correct Stage subclass from a config dict."""
    stage_type = cfg["type"]

    if stage_type == "mandatory_check":
        return MandatoryCheckStage(
            stage_id=cfg["stage_id"],
            rule_expr=cfg["rule"],
            on_success=cfg["on_success"],
            on_failure=cfg["on_failure"],
        )

    if stage_type == "external_dependency":
        return ExternalDependencyStage(
            stage_id=cfg["stage_id"],
            action=cfg["action"],
            retry_count=cfg.get("retry_count", 3),
            on_success=cfg["on_success"],
            on_failure=cfg["on_failure"],
        )

    if stage_type == "threshold_check":
        return ThresholdCheckStage(
            stage_id=cfg["stage_id"],
            variable=cfg["variable"],
            branches=cfg["branches"],
        )

    raise ValueError(f"Unknown stage type: {stage_type!r}")


# ---------------------------------------------------------------------------
# Rule Engine
# ---------------------------------------------------------------------------
class RuleEngine:
    """Loads a JSON workflow config and evaluates applications stage-by-stage."""

    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.workflow_name: str = ""
        self.version: str = ""
        self.stages: list[Stage] = []
        self._load_config()

    # -- private helpers -----------------------------------------------------

    def _load_config(self) -> None:
        path = Path(self.config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(path, "r", encoding="utf-8") as fh:
            config = json.load(fh)

        self.workflow_name = config.get("workflow_name", "Unnamed Workflow")
        self.version = config.get("version", "0.0")
        self.stages = [_build_stage(s) for s in config.get("stages", [])]

    def get_external_stage(self) -> Optional[ExternalDependencyStage]:
        """Return the first external_dependency stage, if any."""
        for stage in self.stages:
            if isinstance(stage, ExternalDependencyStage):
                return stage
        return None

    # -- public API ----------------------------------------------------------

    def evaluate(self, application_id: str, data: dict) -> tuple[str, str]:
        """
        Run *data* through every stage in order.

        Returns
        -------
        (decision, reason) — e.g. ("APPROVED", "credit_score=750 >= 750")

        Side-effect: writes each step to AuditLog.
        """
        insert_audit_log(
            application_id=application_id,
            action="ENGINE_START",
            result=f"Starting workflow '{self.workflow_name}' v{self.version}",
        )

        for stage in self.stages:
            outcome, detail = stage.evaluate(data)

            insert_audit_log(
                application_id=application_id,
                action=f"STAGE_{stage.stage_id}_EVALUATED",
                rule_triggered=f"{stage.stage_type} (stage {stage.stage_id})",
                result=f"{outcome}: {detail}",
            )

            if outcome.lower() != "next":
                # Terminal decision reached
                insert_audit_log(
                    application_id=application_id,
                    action="DECISION_REACHED",
                    rule_triggered=f"stage {stage.stage_id}",
                    result=f"{outcome}: {detail}",
                )
                return outcome, detail

        # All stages passed with "next" — should not happen with a valid config
        insert_audit_log(
            application_id=application_id,
            action="DECISION_REACHED",
            rule_triggered=None,
            result="MANUAL_REVIEW: All stages passed without terminal decision",
        )
        return "MANUAL_REVIEW", "All stages passed without terminal decision"
