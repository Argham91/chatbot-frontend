"""
ai_insights_service.py
======================
Hybrid AI Insights service for Equipment Health dashboard.

Architecture (Option B — Hybrid):
  Step 1  →  Python computes ALL metrics deterministically from the DB
              (MTBF, MTTR, health score, breakdown prediction, repeat parts)
  Step 2  →  A ~500-token structured JSON context is sent to the LLM
              (OpenAI gpt-4o-mini  OR  Anthropic claude-3-sonnet)
  Step 3  →  LLM generates only narratives + insight text — no arithmetic
  Step 4  →  Merged response returned to frontend

Key design principles:
- Zero hardcoding — all thresholds / model names come from .env
- Only BREAKDOWN = 'X' rows are analysed (planned maintenance excluded)
- ReadOnlyGuard in EquipmentDBService ensures no DB writes
- Single LLM call (no tool loop) → fast, cheap, predictable latency
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
from dotenv import load_dotenv

from db_equipment_service import EquipmentDBService

load_dotenv()
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# LLM SYSTEM PROMPT — instructs the model to only narrate, never compute
# ═══════════════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """You are an expert equipment health analyst for a heavy mining operation.
You will receive pre-computed metrics for one piece of mining equipment.

CRITICAL RULES:
1. ALL numbers are already computed in Python — do NOT recalculate or approximate them.
2. Use EXACT numbers from the input JSON in your text.
3. Be specific and action-oriented: name the system to inspect, state the urgency.
4. Return ONLY valid JSON — no markdown fences, no prose outside the JSON object.
5. ALL costs are in INDIAN RUPEES — always use the ₹ symbol (never $, USD, or INR text).

Return EXACTLY this JSON structure (no extra keys):
{
  "insights": [
    {
      "category": "<one of: MTBF Trend | Repeat Failure | Downtime Impact | Cost Alert | Availability | Failure Pattern | Part Life Analysis>",
      "severity": "<HIGH | MEDIUM | LOW>",
      "title": "<8-12 words max>",
      "detail": "<1-2 sentences using exact numbers from context>",
      "action": "<1 sentence: what to do, which system, by when>"
    }
  ],
  "prediction_narrative": "<2-3 sentences explaining the next breakdown prediction and confidence>",
  "checkpoint_recommendation": "<2-3 sentences: specific systems to inspect, recommended date, why>"
}

Generate exactly 5 insights covering DIFFERENT aspects of equipment health.
MANDATORY: Include at least ONE insight with category "Part Life Analysis".
  — Analyse parts_life_analysis: identify which parts are replaced most frequently,
    state their avg_life_days and times_replaced, and explain whether the replacement
    frequency indicates premature failure, normal wear, or scheduled maintenance.
  — Flag parts with avg_life_days < 90 as potential reliability concerns.
Severity distribution should reflect the actual data (not all HIGH, not all LOW)."""


# ═══════════════════════════════════════════════════════════════════════════════
# Helper utilities
# ═══════════════════════════════════════════════════════════════════════════════

def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _safe_dt(v: Any) -> Optional[datetime]:
    """Parse a datetime string or datetime object → datetime, or None."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _parse_date(s: Optional[str], default: datetime) -> datetime:
    if not s:
        return default
    dt = _safe_dt(s)
    return dt if dt else default


# ═══════════════════════════════════════════════════════════════════════════════
# AIInsightsService
# ═══════════════════════════════════════════════════════════════════════════════

class AIInsightsService:
    """
    Computes equipment health metrics from the DB (Python math, no LLM)
    then calls the configured LLM once to generate actionable insights.
    """

    def __init__(self, db_svc: EquipmentDBService, equip_kpis: Optional[Any] = None) -> None:
        self.db_svc       = db_svc
        self.equip_kpis   = equip_kpis   # EquipmentKPIs instance — used for fuel/running-hours data

        # ── LLM provider config (all from .env) ──────────────────────────────
        self.provider          = os.getenv("INSIGHTS_PROVIDER",          "openai").lower()
        self.model_openai      = os.getenv("INSIGHTS_MODEL_OPENAI",      "gpt-4o-mini")
        self.model_anthropic   = os.getenv("INSIGHTS_MODEL_ANTHROPIC",   "claude-3-sonnet-20240229")
        self.max_tokens        = int(os.getenv("INSIGHTS_MAX_TOKENS",    "1500"))
        # Enforce minimum 30-second timeout so gpt-4o-mini never times out on
        # reasonable requests (default env value of 15 is too short)
        self.timeout_sec       = max(int(os.getenv("INSIGHTS_TIMEOUT",   "45")), 30)
        self.litellm_api_key   = os.getenv("LITELLM_API_KEY",  "").strip()
        self.litellm_base_url  = os.getenv("LITELLM_BASE_URL", "http://80.9.2.70:4000").strip()

        # ── Health-score penalty thresholds (overrideable via .env) ──────────
        self.penalty_worsening_trend   = int(os.getenv("EHI_PENALTY_WORSENING",   "15"))
        self.penalty_avail_below_90    = int(os.getenv("EHI_PENALTY_AVAIL_90",    "20"))
        self.penalty_avail_below_95    = int(os.getenv("EHI_PENALTY_AVAIL_95",    "10"))
        self.penalty_mttr_over_24      = int(os.getenv("EHI_PENALTY_MTTR_24",     "10"))
        self.penalty_mttr_over_12      = int(os.getenv("EHI_PENALTY_MTTR_12",     "5"))
        self.penalty_repeat_part_each  = int(os.getenv("EHI_PENALTY_REPEAT_PART", "8"))
        self.penalty_repeat_part_max   = int(os.getenv("EHI_PENALTY_REPEAT_MAX",  "24"))
        self.penalty_bd_over_30        = int(os.getenv("EHI_PENALTY_BD_30",       "10"))
        self.penalty_bd_over_15        = int(os.getenv("EHI_PENALTY_BD_15",       "5"))
        self.bonus_improving_trend     = int(os.getenv("EHI_BONUS_IMPROVING",     "10"))

        # ── Prediction risk thresholds (days) ────────────────────────────────
        self.risk_high_days   = int(os.getenv("EHI_RISK_HIGH_DAYS",   "7"))
        self.risk_medium_days = int(os.getenv("EHI_RISK_MEDIUM_DAYS", "21"))

        # ── Checkpoint lead time (days before predicted breakdown) ────────────
        self.checkpoint_lead_days = int(os.getenv("EHI_CHECKPOINT_LEAD_DAYS", "3"))

        # ── In-memory response cache (keyed by equip+date range) ──────────────
        # Prevents repeated LLM calls when a manager views the same equipment
        # multiple times in a session.  TTL default: 15 minutes.
        self._cache: Dict[str, Tuple[datetime, Dict]] = {}
        self._cache_ttl = timedelta(
            minutes=int(os.getenv("INSIGHTS_CACHE_TTL_MINUTES", "15"))
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Step 1 — Python metric computation (accurate, deterministic)
    # ──────────────────────────────────────────────────────────────────────────

    def _compute_metrics(
        self,
        equipment_code: str,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> Dict[str, Any]:
        """
        Fetches breakdown history + parts data from the DB and computes every
        metric in Python.  The LLM never touches raw numbers — it only
        receives the final structured dict from this method.
        """
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        # ── Date range ────────────────────────────────────────────────────────
        start_dt = _parse_date(start_date, today - timedelta(days=365))
        end_dt   = _parse_date(end_date,   today)
        calendar_days  = max((end_dt - start_dt).days + 1, 1)
        calendar_hours = calendar_days * 24

        # ── Fetch data from DB ────────────────────────────────────────────────
        bd_response = self.db_svc.get_breakdown_history(equipment_code, start_date, end_date)
        all_rows    = bd_response.get("breakdowns", [])

        # ONLY breakdown rows — exclude planned maintenance notifications
        bd_rows = [b for b in all_rows if b.get("is_breakdown")]
        bd_rows_asc = sorted(
            bd_rows,
            key=lambda b: _safe_dt(b.get("malfunction_start")) or datetime.min,
        )

        # Parts data — for repeat failure detection
        parts_response = self.db_svc.get_parts_replaced(equipment_code, start_date, end_date)
        all_parts      = parts_response.get("parts", [])

        # Cause distribution (already filtered to BREAKDOWN='X' in DB query)
        cause_dist = bd_response.get("cause_distribution", [])

        # ── Core KPIs ─────────────────────────────────────────────────────────
        num_breakdowns      = len(bd_rows)
        total_downtime      = sum(_safe_float(b.get("duration_hrs")) for b in bd_rows)
        total_notifications = len(all_rows)

        # ── Repair cost: use parts_response total, NOT per-row breakdown_cost ──
        # Root cause of zero: get_breakdown_history() joins costing via ORDER_NO
        # on each notification row, but most breakdown notifications have
        # ORDER_NO = NULL or '000000000000' → LEFT JOIN finds nothing → cost = 0.
        #
        # get_parts_replaced() (already fetched above) uses a UNION bridge:
        #   mm_plant_maint_calibration (EQUIPMENT_NO → ORDER_NO)
        #   + zpm_iw29_notifications  (EQUIPMENT    → ORDER_NO)
        # → mm_plant_maint_costing
        # This matches exactly what the Equipment Profile section displays.
        parts_total = _safe_float(
            parts_response.get("summary", {}).get("total_parts_cost", 0)
        )
        # Fall back to per-row sum only if parts query returned nothing
        per_row_sum   = sum(_safe_float(b.get("breakdown_cost")) for b in bd_rows)
        total_repair_cost = parts_total if parts_total > 0 else per_row_sum

        mttr_hours   = round(total_downtime / num_breakdowns, 2) if num_breakdowns else 0.0
        mtbf_hours   = round((calendar_hours - total_downtime) / num_breakdowns, 2) if num_breakdowns else 0.0
        availability = round(((calendar_hours - total_downtime) / calendar_hours) * 100, 2)
        avg_cost_per_breakdown = round(total_repair_cost / num_breakdowns, 2) if num_breakdowns else 0.0

        # ── Monthly breakdown counts & MTBF trend ─────────────────────────────
        monthly_counts: Dict[str, int] = {}
        monthly_downtime: Dict[str, float] = {}
        for b in bd_rows:
            month = str(b.get("malfunction_start", ""))[:7]
            if month and len(month) == 7:
                monthly_counts[month]   = monthly_counts.get(month, 0) + 1
                monthly_downtime[month] = monthly_downtime.get(month, 0.0) + _safe_float(b.get("duration_hrs"))

        sorted_months = sorted(monthly_counts.keys())
        monthly_breakdown_counts = [{"month": m, "count": monthly_counts[m]} for m in sorted_months]

        # MTBF per month (approximate: assume equal calendar hours per month = 720)
        hours_per_month = 720
        monthly_mtbf: Dict[str, float] = {}
        for m in sorted_months:
            cnt = monthly_counts[m]
            dt  = monthly_downtime.get(m, 0.0)
            if cnt > 0:
                monthly_mtbf[m] = round((hours_per_month - dt) / cnt, 1)

        # Trend: compare last 3 months MTBF
        last_3_months  = sorted_months[-3:] if len(sorted_months) >= 3 else sorted_months
        last_3_mtbf    = [monthly_mtbf.get(m, 0.0) for m in last_3_months]
        trend_direction = "stable"
        if len(last_3_mtbf) >= 2:
            if last_3_mtbf[-1] < last_3_mtbf[0] * 0.85:   # 15% decline
                trend_direction = "worsening"
            elif last_3_mtbf[-1] > last_3_mtbf[0] * 1.15: # 15% improvement
                trend_direction = "improving"

        # ── Next breakdown prediction ──────────────────────────────────────────
        prediction = self._predict_next_breakdown(
            bd_rows_asc, trend_direction, today
        )

        # ── Top failure cause ─────────────────────────────────────────────────
        top_cause: Dict[str, Any] = {}
        if cause_dist:
            top     = cause_dist[0]
            cause_count = int(top.get("count", 0))
            pct = round(cause_count / num_breakdowns * 100, 1) if num_breakdowns else 0.0
            top_cause = {
                "cause":        top.get("cause", "Not Specified"),
                "count":        cause_count,
                "pct_of_total": pct,
            }

        # ── Repeat part failures (any order type, replaced > 1 time) ─────────
        # Note: In this DB, all cost records use order_type "PREVENTIVE
        # MAINTENANCE ORDER" even for breakdown events, so filtering by
        # order_type would always yield an empty list — we include all parts.
        repeat_parts: List[Dict[str, Any]] = []
        for p in all_parts:
            times_used = int(p.get("times_used") or 0)
            if times_used > 1:
                repeat_parts.append({
                    "material":       p.get("material_desc", "Unknown"),
                    "replaced_times": times_used,
                    "total_cost":     round(_safe_float(p.get("total_cost")), 0),
                    "last_used":      str(p.get("last_used_date", "")),
                })
        # Sort by replaced_times DESC, take top 3
        repeat_parts.sort(key=lambda x: x["replaced_times"], reverse=True)
        repeat_parts = repeat_parts[:3]

        # ── Parts Life Analysis ───────────────────────────────────────────────
        # For each part, estimate average life = calendar_days / times_replaced.
        # This tells us how often each component is consumed and whether
        # replacement frequency is normal wear or premature failure.
        parts_life_analysis: List[Dict[str, Any]] = []
        for p in all_parts:
            times_used = int(p.get("times_used") or 0)
            if times_used >= 1:
                avg_life_days = round(calendar_days / times_used, 1)
                # Concern level: HIGH = replaced more than once a month
                if avg_life_days < 30:
                    concern_level = "HIGH"
                elif avg_life_days < 90:
                    concern_level = "MEDIUM"
                else:
                    concern_level = "LOW"
                parts_life_analysis.append({
                    "material":       p.get("material_desc", "Unknown"),
                    "uom":            str(p.get("uom", "")),
                    "times_replaced": times_used,
                    "avg_life_days":  avg_life_days,
                    "total_qty":      round(_safe_float(p.get("total_qty")), 2),
                    "total_cost":     round(_safe_float(p.get("total_cost")), 2),
                    "last_replaced":  str(p.get("last_used_date", "")),
                    "order_type":     str(p.get("order_type_desc", "")),
                    "concern_level":  concern_level,
                })
        # Sort by times_replaced DESC (most frequently replaced first)
        parts_life_analysis.sort(key=lambda x: x["times_replaced"], reverse=True)

        # ── Health Score + Risk Level (computed together for alignment) ───────
        days_until_next = prediction.get("days_until_next_breakdown")
        health_score, risk_level = self._compute_health_score(
            trend_direction=trend_direction,
            availability_pct=availability,
            mttr_hours=mttr_hours,
            all_parts=all_parts,
            num_breakdowns=num_breakdowns,
            calendar_days=calendar_days,
            days_until_next=days_until_next,
            avg_cost_per_breakdown=avg_cost_per_breakdown,
        )

        return {
            "num_breakdowns":          num_breakdowns,
            "total_notifications":     total_notifications,
            "total_downtime_hrs":      round(total_downtime, 2),
            "mttr_hours":              mttr_hours,
            "mtbf_hours":              mtbf_hours,
            "availability_pct":        availability,
            "total_repair_cost":       round(total_repair_cost, 2),
            "avg_cost_per_breakdown":  avg_cost_per_breakdown,
            "calendar_hours":          calendar_hours,
            "calendar_days":           calendar_days,
            "trend_direction":         trend_direction,
            "last_3_months_mtbf":      last_3_mtbf,
            "last_3_months_labels":    last_3_months,
            "monthly_breakdown_counts": monthly_breakdown_counts,
            "top_failure_cause":       top_cause,
            "repeat_part_failures":    repeat_parts,
            "parts_life_analysis":     parts_life_analysis,
            "prediction":              prediction,
            "health_score":            health_score,
            "risk_level":              risk_level,
        }

    def _predict_next_breakdown(
        self,
        bd_rows_asc: List[Dict],
        trend_direction: str,
        today: datetime,
    ) -> Dict[str, Any]:
        """
        Predicts the next breakdown date from inter-breakdown intervals.
        Uses recent intervals if trend is worsening (more conservative).
        """
        if len(bd_rows_asc) < 2:
            # Not enough history → cannot predict
            last_bd_date = ""
            if bd_rows_asc:
                dt = _safe_dt(bd_rows_asc[-1].get("malfunction_start"))
                last_bd_date = dt.strftime("%Y-%m-%d") if dt else ""
            return {
                "last_breakdown_date":             last_bd_date,
                "predicted_next_breakdown_date":   None,
                "days_until_next_breakdown":       None,
                "recommended_checkpoint_date":     None,
                "avg_interval_days":               None,
                "basis":                           "insufficient_history",
                "confidence":                      "LOW",
            }

        # Build intervals (hours) between consecutive breakdowns
        intervals_hrs: List[float] = []
        for i in range(1, len(bd_rows_asc)):
            prev_dt = _safe_dt(bd_rows_asc[i - 1].get("malfunction_start"))
            curr_dt = _safe_dt(bd_rows_asc[i].get("malfunction_start"))
            if prev_dt and curr_dt and curr_dt > prev_dt:
                delta_hrs = (curr_dt - prev_dt).total_seconds() / 3600
                intervals_hrs.append(delta_hrs)

        if not intervals_hrs:
            return {
                "last_breakdown_date":           "",
                "predicted_next_breakdown_date": None,
                "days_until_next_breakdown":     None,
                "recommended_checkpoint_date":   None,
                "avg_interval_days":             None,
                "basis":                         "no_valid_intervals",
                "confidence":                    "LOW",
            }

        # Choose interval basis: recent 3 if trend worsening (more conservative)
        if trend_direction == "worsening" and len(intervals_hrs) >= 3:
            chosen_intervals = intervals_hrs[-3:]
            basis = "recent_3_intervals"
            confidence = "MEDIUM"
        else:
            chosen_intervals = intervals_hrs
            basis = "all_intervals"
            confidence = "HIGH" if len(intervals_hrs) >= 5 else "MEDIUM"

        avg_interval_hrs  = mean(chosen_intervals)
        avg_interval_days = round(avg_interval_hrs / 24, 1)

        # Last breakdown datetime
        last_bd_dt   = _safe_dt(bd_rows_asc[-1].get("malfunction_start"))
        if not last_bd_dt:
            last_bd_dt = today

        predicted_next_dt         = last_bd_dt + timedelta(hours=avg_interval_hrs)
        days_until                = (predicted_next_dt.date() - today.date()).days
        recommended_checkpoint_dt = predicted_next_dt - timedelta(days=self.checkpoint_lead_days)

        return {
            "last_breakdown_date":             last_bd_dt.strftime("%Y-%m-%d"),
            "predicted_next_breakdown_date":   predicted_next_dt.strftime("%Y-%m-%d"),
            "days_until_next_breakdown":       days_until,
            "recommended_checkpoint_date":     recommended_checkpoint_dt.strftime("%Y-%m-%d"),
            "avg_interval_days":               avg_interval_days,
            "basis":                           basis,
            "confidence":                      confidence,
        }

    def _compute_health_score(
        self,
        trend_direction: str,
        availability_pct: float,
        mttr_hours: float,
        all_parts: List[Dict],
        num_breakdowns: int,
        calendar_days: int,
        days_until_next: Optional[int],
        avg_cost_per_breakdown: float,
    ) -> Tuple[int, str]:
        """
        Comprehensive health score (0–100) + aligned risk level.

        Seven penalty categories (max penalties shown):
          A. Availability          (0 to −30 pts) — core reliability metric
          B. Breakdown frequency   (0 to −20 pts) — breakdowns per month
          C. MTBF trend direction  (−12 to +8 pts) — trajectory matters
          D. MTTR severity         (0 to −12 pts) — how fast failures are fixed
          E. Prediction proximity  (0 to −15 pts) — imminent / overdue breakdown
          F. Avg cost per breakdown(0 to −10 pts) — high cost = component damage
          G. High-freq parts       (0 to −8 pts)  — parts replaced ≥3× in period

        Risk level is DERIVED from the final score (never computed separately):
          score ≥ 80  → LOW
          score 60–79 → MEDIUM
          score < 60  → HIGH

        This ensures the health score and risk badge ALWAYS align — no more
        "90/100 but HIGH Risk" inconsistencies.
        """
        score = 100

        # A. Availability — most critical reliability metric for mining equipment
        if availability_pct < 80:
            score -= 30
        elif availability_pct < 85:
            score -= 22
        elif availability_pct < 90:
            score -= 15
        elif availability_pct < 95:
            score -= 8
        elif availability_pct < 98:
            score -= 3

        # B. Breakdown frequency (breakdowns per month in the analysis period)
        months_in_period = max(calendar_days / 30.0, 1.0)
        bd_per_month = num_breakdowns / months_in_period
        if bd_per_month > 5:
            score -= 20
        elif bd_per_month > 3:
            score -= 15
        elif bd_per_month > 2:
            score -= 10
        elif bd_per_month > 1:
            score -= 5

        # C. MTBF trend direction — trajectory predicts future reliability
        if trend_direction == "worsening":
            score -= 12
        elif trend_direction == "improving":
            score += 8

        # D. MTTR — longer average repairs = more production impact
        if mttr_hours > 48:
            score -= 12
        elif mttr_hours > 24:
            score -= 8
        elif mttr_hours > 12:
            score -= 4

        # E. Prediction proximity — breakdown imminent or statistically overdue
        if days_until_next is not None:
            if days_until_next <= 0:
                score -= 15   # overdue: breakdown was statistically due in the past
            elif days_until_next <= 7:
                score -= 12
            elif days_until_next <= 14:
                score -= 8
            elif days_until_next <= 21:
                score -= 4

        # F. Avg repair cost per breakdown — high cost signals severe component damage
        if avg_cost_per_breakdown > 15000:
            score -= 10
        elif avg_cost_per_breakdown > 8000:
            score -= 6
        elif avg_cost_per_breakdown > 3000:
            score -= 3

        # G. High-frequency parts (replaced ≥ 3× in the period) → premature wear signal
        high_freq_count = sum(
            1 for p in all_parts if int(p.get("times_used") or 0) >= 3
        )
        score -= min(high_freq_count * 4, 8)

        final_score = max(0, min(100, score))

        # Risk level derived from score — guarantees alignment with health badge
        if final_score >= 80:
            risk_level = "LOW"
        elif final_score >= 60:
            risk_level = "MEDIUM"
        else:
            risk_level = "HIGH"

        return final_score, risk_level

    # ──────────────────────────────────────────────────────────────────────────
    # Step 1b — Operational data: engine hours, fuel, distance from truck_reports
    # ──────────────────────────────────────────────────────────────────────────

    def _get_operational_data(
        self,
        equipment_name: str,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """
        Fetches engine hours, fuel consumption, distance and fuel efficiency
        for the equipment from EquipmentKPIs.fleet_details() (truck_reports DB).

        Uses case-insensitive, partial-match lookup on equipment_name so that
        'EX-1' matches 'ex-1' or 'EX1' in the DB.

        Returns None if EquipmentKPIs is unavailable or no matching row found.
        """
        if self.equip_kpis is None:
            return None
        if not start_date or not end_date:
            return None
        try:
            fleet_data = self.equip_kpis.fleet_details(start_date, end_date)
            if not fleet_data:
                return None

            # Case-insensitive partial match (covers "TIPPER-1" ↔ "TIPPER1" etc.)
            name_lower = equipment_name.lower().strip()
            matched: Optional[Dict[str, Any]] = None
            for row in fleet_data:
                row_name = str(row.get("equipment_name", "")).lower().strip()
                if row_name == name_lower or row_name in name_lower or name_lower in row_name:
                    matched = row
                    break

            if matched is None:
                logger.debug(
                    "[AIInsights] No operational data row matched equipment_name='%s' in fleet_details.",
                    equipment_name,
                )
                return None

            return {
                "engine_hours_total":    round(float(matched.get("engine_hours", 0) or 0), 2),
                "in_motion_hours_total": round(float(matched.get("in_motion_engine_hours", 0) or 0), 2),
                "idle_hours_total":      round(float(matched.get("idle_hours", 0) or 0), 2),
                "total_distance_km":     round(float(matched.get("distance", 0) or 0), 2),
                "fuel_consumed_liters":  round(float(matched.get("fuel_consumed", 0) or 0), 2),
                "fuel_efficiency_kmpl":  round(float(matched.get("kmpl", 0) or 0), 2),
                "availability_pct":      round(float(matched.get("availability", 0) or 0), 2),
            }
        except Exception as exc:
            logger.warning(
                "[AIInsights] Failed to fetch operational data for '%s': %s",
                equipment_name, exc,
            )
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # Step 2 — Build compact LLM context JSON (~500 tokens)
    # ──────────────────────────────────────────────────────────────────────────

    def _build_context_json(
        self,
        metrics: Dict[str, Any],
        equipment_code: str,
        equipment_name: str,
        equipment_type: str,
        start_date: Optional[str],
        end_date: Optional[str],
        operational_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        pred = metrics["prediction"]
        context: Dict[str, Any] = {
            "equipment": {
                "code":  equipment_code,
                "name":  equipment_name,
                "type":  equipment_type,
            },
            "date_range": {
                "start": start_date or "",
                "end":   end_date   or "",
                "days":  metrics["calendar_hours"] // 24,
            },
            "breakdown_metrics": {
                "total_breakdowns":        metrics["num_breakdowns"],
                "total_notifications":     metrics["total_notifications"],
                "total_downtime_hrs":      metrics["total_downtime_hrs"],
                "mttr_hours":              metrics["mttr_hours"],
                "mtbf_hours":              metrics["mtbf_hours"],
                "availability_pct":        metrics["availability_pct"],
                "avg_cost_per_breakdown":  metrics["avg_cost_per_breakdown"],
                "total_repair_cost":       metrics["total_repair_cost"],
            },
            "trend": {
                "direction":               metrics["trend_direction"],
                "last_3_months_labels":    metrics["last_3_months_labels"],
                "last_3_months_mtbf_hrs":  metrics["last_3_months_mtbf"],
                "monthly_breakdown_counts": metrics["monthly_breakdown_counts"][-6:],
            },
            "top_failure_cause":    metrics["top_failure_cause"],
            "repeat_part_failures": metrics["repeat_part_failures"],
            "prediction": {
                "last_breakdown_date":           pred.get("last_breakdown_date"),
                "predicted_next_breakdown_date": pred.get("predicted_next_breakdown_date"),
                "days_until_next_breakdown":     pred.get("days_until_next_breakdown"),
                "recommended_checkpoint_date":   pred.get("recommended_checkpoint_date"),
                "avg_interval_days":             pred.get("avg_interval_days"),
                "basis":                         pred.get("basis"),
                "confidence":                    pred.get("confidence"),
            },
            "computed_health_score": metrics["health_score"],
            "risk_level":            metrics["risk_level"],
            # Parts life analysis — for LLM Part Life Analysis insight generation
            "parts_life_analysis":   metrics.get("parts_life_analysis", []),
        }
        # ── Merge operational data (engine hours, fuel, distance) if available ─
        if operational_data:
            context["operational_data"] = operational_data
        return json.dumps(context, ensure_ascii=False, default=str)

    # ──────────────────────────────────────────────────────────────────────────
    # Step 3 — LLM API calls (OpenAI or Anthropic)
    # ──────────────────────────────────────────────────────────────────────────

    async def _call_openai(self, context_json: str) -> Dict[str, Any]:
        """Calls LiteLLM proxy (OpenAI-compatible) for all providers."""
        url  = f"{self.litellm_base_url}/chat/completions"
        model = os.getenv("CHATBOT_MODEL", self.model_openai)
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": context_json},
            ],
            "max_tokens":      self.max_tokens,
            "temperature":     0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.litellm_api_key}",
            "Content-Type":  "application/json",
        }
        last_exc: Exception = RuntimeError("LiteLLM call failed — no attempts made")
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                    r = await client.post(url, json=body, headers=headers)
                    r.raise_for_status()
                    raw = r.json()["choices"][0]["message"]["content"]
                    return json.loads(raw)
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "[AIInsights] LiteLLM attempt %d/%d failed for model=%s: %s",
                    attempt + 1, 2, model, exc,
                )
                if attempt == 0:
                    await asyncio.sleep(3)
        raise last_exc

    async def _call_anthropic(self, context_json: str) -> Dict[str, Any]:
        """Routes through LiteLLM — same OpenAI-compatible format."""
        return await self._call_openai(context_json)

    # ──────────────────────────────────────────────────────────────────────────
    # Public entry point
    # ──────────────────────────────────────────────────────────────────────────

    async def generate_insights(
        self,
        equipment_code: str,
        equipment_name: str,
        equipment_type: str,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> Dict[str, Any]:
        """
        Main method called by the FastAPI endpoint.

        1. Compute all metrics in Python (deterministic, no LLM).
        2. Build compact JSON context.
        3. Call LLM once → narratives + insight cards.
        4. Merge and return final response.
        """
        # ── 0. Cache check — avoid repeat LLM calls for same equipment+range ───
        cache_key = f"{equipment_code}|{start_date or ''}|{end_date or ''}"
        now_utc   = datetime.utcnow()
        if cache_key in self._cache:
            expires_at, cached_result = self._cache[cache_key]
            if now_utc < expires_at:
                remaining = int((expires_at - now_utc).total_seconds())
                logger.info(
                    "[AIInsights] Cache HIT for %s (expires in %ds).",
                    cache_key, remaining,
                )
                return cached_result
            else:
                # Expired — remove stale entry
                del self._cache[cache_key]

        # ── 1. Compute metrics ─────────────────────────────────────────────────
        try:
            metrics = self._compute_metrics(equipment_code, start_date, end_date)
        except Exception as exc:
            logger.error("[AIInsights] Metric computation failed for %s: %s", equipment_code, exc)
            raise

        # ── 1b. Early exit: no breakdowns in selected range ────────────────────
        if metrics["num_breakdowns"] == 0:
            logger.info(
                "[AIInsights] No breakdowns for %s in range %s → %s — skipping LLM.",
                equipment_code, start_date, end_date,
            )
            model_used = self.model_openai if self.provider == "openai" else self.model_anthropic
            return {
                "equipment_code":  equipment_code,
                "equipment_name":  equipment_name,
                "equipment_type":  equipment_type,
                "date_range":      {"start": start_date, "end": end_date},
                "no_data":         True,
                "no_data_message": "No breakdown recorded in the selected Date Range.",
                "health_score":    100,
                "risk_level":      "LOW",
                "metrics_summary": {
                    "total_breakdowns":       0,
                    "total_notifications":    metrics["total_notifications"],
                    "total_downtime_hrs":     0,
                    "mttr_hours":             0,
                    "mtbf_hours":             0,
                    "availability_pct":       100.0,
                    "total_repair_cost":      0,
                    "avg_cost_per_breakdown": 0,
                    "trend_direction":        "stable",
                    "top_failure_cause":      {},
                    "repeat_part_failures":   [],
                    "parts_life_analysis":    [],
                    "monthly_breakdown_counts": [],
                },
                "prediction":              metrics["prediction"],
                "insights":                [],
                "prediction_narrative":    "",
                "checkpoint_recommendation": "",
                "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
                "provider":  self.provider,
                "model":     model_used,
            }

        # ── 1c. Fetch operational data (engine hours, fuel, distance) ──────────
        operational_data = self._get_operational_data(equipment_name, start_date, end_date)
        if operational_data:
            logger.info(
                "[AIInsights] Operational data found for '%s': engine_hrs=%.1f fuel=%.1f km=%.1f",
                equipment_name,
                operational_data.get("engine_hours_total", 0),
                operational_data.get("fuel_consumed_liters", 0),
                operational_data.get("total_distance_km", 0),
            )
        else:
            logger.info("[AIInsights] No operational data available for '%s'.", equipment_name)

        # ── 2. Build context JSON ──────────────────────────────────────────────
        context_json = self._build_context_json(
            metrics, equipment_code, equipment_name, equipment_type,
            start_date, end_date, operational_data,
        )
        logger.info(
            "[AIInsights] context_json for %s (%s chars) built; calling %s…",
            equipment_code, len(context_json), self.provider,
        )

        # ── 3. Call LLM ────────────────────────────────────────────────────────
        llm_response: Dict[str, Any] = {}
        model_used = self.model_openai if self.provider == "openai" else self.model_anthropic

        try:
            if self.provider == "anthropic":
                llm_response = await self._call_anthropic(context_json)
            else:
                llm_response = await self._call_openai(context_json)
        except Exception as exc:
            # Surface the real reason so the frontend can show it (not just "unavailable")
            exc_type  = type(exc).__name__
            exc_short = str(exc)[:200]
            logger.warning(
                "[AIInsights] LLM call failed for %s (%s): %s — returning metric-only response",
                equipment_code, exc_type, exc_short,
            )
            llm_response = {
                "insights": [],
                "prediction_narrative":      f"AI narrative unavailable ({exc_type}). Metrics above are computed by Python and are accurate.",
                "checkpoint_recommendation": f"LLM error: {exc_short[:120]}. Please retry.",
            }

        # ── 4. Validate + normalise LLM insights ──────────────────────────────
        raw_insights = llm_response.get("insights", [])
        valid_severities = {"HIGH", "MEDIUM", "LOW"}
        insights: List[Dict[str, Any]] = []
        for item in raw_insights[:5]:
            sev = str(item.get("severity", "LOW")).upper()
            if sev not in valid_severities:
                sev = "LOW"
            # Safety: replace any dollar signs with ₹ — all costs are Indian Rupees
            def _inr(text: str) -> str:
                return str(text).replace("$", "₹").replace("USD", "₹").replace("INR ", "₹")
            insights.append({
                "category": str(item.get("category", "General")),
                "severity":  sev,
                "title":     _inr(item.get("title", "")),
                "detail":    _inr(item.get("detail", "")),
                "action":    _inr(item.get("action", "")),
            })
        # Also sanitise narrative fields
        def _inr_str(text: str) -> str:
            return str(text).replace("$", "₹").replace("USD", "₹").replace("INR ", "₹")

        # ── 5. Assemble final response ─────────────────────────────────────────
        pred = metrics["prediction"]
        result = {
            "equipment_code":  equipment_code,
            "equipment_name":  equipment_name,
            "equipment_type":  equipment_type,
            "date_range": {
                "start": start_date,
                "end":   end_date,
            },
            "health_score": metrics["health_score"],
            "risk_level":   metrics["risk_level"],
            "metrics_summary": {
                "total_breakdowns":       metrics["num_breakdowns"],
                "total_notifications":    metrics["total_notifications"],
                "total_downtime_hrs":     metrics["total_downtime_hrs"],
                "mttr_hours":             metrics["mttr_hours"],
                "mtbf_hours":             metrics["mtbf_hours"],
                "availability_pct":       metrics["availability_pct"],
                "total_repair_cost":      metrics["total_repair_cost"],
                "avg_cost_per_breakdown": metrics["avg_cost_per_breakdown"],
                "trend_direction":        metrics["trend_direction"],
                "top_failure_cause":      metrics["top_failure_cause"],
                "repeat_part_failures":   metrics["repeat_part_failures"],
                "parts_life_analysis":    metrics.get("parts_life_analysis", []),
                "monthly_breakdown_counts": metrics["monthly_breakdown_counts"],
            },
            "prediction": pred,
            "insights":   insights,
            "prediction_narrative":      _inr_str(llm_response.get("prediction_narrative",      "")),
            "checkpoint_recommendation": _inr_str(llm_response.get("checkpoint_recommendation", "")),
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
            "provider":     self.provider,
            "model":        model_used,
        }

        # ── 6. Store in cache ──────────────────────────────────────────────────
        self._cache[cache_key] = (now_utc + self._cache_ttl, result)
        logger.info(
            "[AIInsights] Response cached for %s (TTL %d min).",
            cache_key, int(self._cache_ttl.total_seconds() / 60),
        )

        return result
