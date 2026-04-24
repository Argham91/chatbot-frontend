"""
chatbot/service.py

ChatbotService — core logic for the IMOS AI Chatbot.

Supports two AI providers (switchable via .env):
  CHATBOT_PROVIDER=openai     → uses OpenAI gpt-4o-mini  (current default)
  CHATBOT_PROVIDER=anthropic  → uses Anthropic Claude     (switch when credits topped up)

Data fetching via Tool Use / Function Calling:
  - OpenAI: Function Calling (multi-turn tool loop)
  - Anthropic: Tool Use (multi-turn tool loop)
  Both providers can call get_production_data, get_quality_data,
  get_equipment_data, get_planning_data, get_daywise_production,
  get_fuel_efficiency — each executes real KPI queries against the DB.

Other fixes:
  - Logs full API error body on non-200 responses
  - Uses safe .replace() substitution so { } in schema never break prompt
  - Truncates schema to MAX_SCHEMA_CHARS to prevent oversized prompt
"""

import json
import logging
import os
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .models import ChatBlock, ChatRequest, ChatResponse
from .schema_registry import SchemaRegistry

logger = logging.getLogger(__name__)

# Max characters of DB schema to inject into system prompt.
MAX_SCHEMA_CHARS = 6000

# Max tool-call iterations per chat turn (prevents infinite loops).
MAX_TOOL_ITERATIONS = 5

# ---------------------------------------------------------------------------
# Apology-response detection
# When GPT generates one of these phrases it means it gave up formatting.
# We detect this and force ONE retry with a correction message.
# ---------------------------------------------------------------------------
_APOLOGY_PHRASES = (
    "had trouble formatting",
    "trouble formatting",
    "fetched the data but",
    "unable to display",
    "couldn't format",
    "could not format",
    "i apologize",
    "please try rephrasing",
    "having difficulty displaying",
    "error formatting",
    "formatting the response",
)

def _looks_like_apology(text: str) -> bool:
    """Return True if the model's text looks like a formatting-failure apology."""
    lower = text.lower()
    return any(phrase in lower for phrase in _APOLOGY_PHRASES)

# ---------------------------------------------------------------------------
# System prompt template
# Uses __PLACEHOLDER__ markers — safe against any { } in DB schema content.
# ---------------------------------------------------------------------------
_SYSTEM_TEMPLATE = """\
You are Mines Assistant — an AI for Integrated Mining Operations System at Kaliapani Mines of Balasore Alloys Limited.
You help mine managers and operators understand production data, quality metrics, equipment
performance, and planning targets.

KEY MINING METRICS:
- ROM (Run of Mine): raw ore extracted from pit, measured in MT (metric tonnes)
- OB (Overburden): waste rock removed to expose ore, measured in BCM (bank cubic metres)
- Cr2O3%: chromite content percentage — higher = better quality ore (Low Grade: <40%, Medium Grade: 40-51.99%, High Grade: >=52%)
- Strip Ratio: BCM of OB removed per MT of ore
- KMPL: vehicle fuel efficiency (km per litre) — mining tippers typically 1.5-3.5 km/L
- Stacking: processed ore stored in stockyards before despatch
- Despatch: ore sent from mine to plant or customer
- Plant Received: ore received and confirmed at processing plant
- HG / MG / LG: High Grade / Medium Grade / Low Grade ore

DASHBOARD NAVIGATION:
- Production page : ROM totals, OB removal, grade-wise breakdown, Cr2O3 trends, location data
- Planning page   : planned vs actual, MRL cutting plan, integrated planning table
- Equipment page  : fleet status, active/inactive vehicles, fuel efficiency, maintenance findings
- Quality page    : end-to-end tracking — Excavation > ROM > Stack > Despatch > Plant Received
- Environment page: environmental monitoring data

DATABASE SCHEMA (auto-discovered — use this to understand available data):
__SCHEMA__

TODAY'S DATE: __TODAY__
DEFAULT PERIOD (use when user does not specify a date): __PREV_START__ to __PREV_END__

=============================================================================
TOOL USE INSTRUCTIONS:
=============================================================================
You have access to tools that fetch REAL live data from the database.

CRITICAL TOOL RULES — MUST FOLLOW WITHOUT EXCEPTION:
1. NEVER ask the user for permission or confirmation before fetching data.
   Just fetch it immediately. "Should I fetch?" or "I can retrieve..." are FORBIDDEN.
2. NEVER say "I would need to review data" — JUST CALL THE TOOL and review it.
3. For BROAD or STRATEGIC questions (e.g. "What are the major issues?",
   "Analyse our performance", "What is causing losses?") — call ALL relevant
   tools (production + planning + equipment) together, then synthesise the answer.
4. ALWAYS call the appropriate tool FIRST, then build your JSON response from the data.
5. If the user says "yes", "go ahead", "fetch it", or any confirmation — this means
   they are responding to something conversational. IGNORE that context and treat
   the ORIGINAL question as your task. Re-fetch data if needed and respond in JSON.

Tool selection guide — use the FIRST matching rule:
- Greetings, casual chat, thanks, help requests (hi, hello, how are you, what can you do, thanks, etc.)
  → answer directly in JSON, NO tool needed. Respond warmly and mention what you can help with.

- FUEL questions (any mention of: fuel, litre, consumption, KMPL, km per litre, vehicle efficiency,
  why fuel high, top fuel consumers, fuel trend, fuel cost) →
  ALWAYS call get_fuel_efficiency FIRST (primary fuel data).
  If question also asks about vehicles / fleet / availability → also call get_equipment_data.
  NEVER answer fuel questions from get_equipment_data alone.

- Equipment / fleet questions (vehicles, active/inactive, maintenance, findings, fleet status,
  availability — with NO mention of fuel or KMPL) → get_equipment_data

- Production questions (ROM, OB, Cr2O3, grades, strip ratio, overburden) → get_production_data
- Quality/pipeline questions (excavation, stacking, despatch, plant received) → get_quality_data
- Planning questions (planned vs actual, MRL plan, targets) → get_planning_data
- Day-wise trends, time series, or daily breakdown → get_daywise_production

- ANALYTICAL questions — why, analyse, reason, cause, gap, deviation, shortfall, underperformance,
  "what happened", "how are we doing", "explain the gap", "why missed target":
  → Identify the domain first (production/fuel/quality/equipment), then call ALL relevant tools
    for that domain together (see ANALYTICAL REASONING section below), then reason over the data.

- Broad / strategic / overall performance review → call ALL tools together
- General mining knowledge (definitions, concepts) → answer directly, no tool needed

=============================================================================
ANALYTICAL REASONING — HOW TO ANSWER "WHY", "ANALYSE", "ASSESS" QUESTIONS:
=============================================================================
When the user uses words like: why, analyse, reason, cause, explain, assess, what happened,
how are we doing, performance, gap, shortfall, underperformance, deviation, issue, problem —
you MUST REASON over the data, not just display it.

Step 1 — FETCH data using the Tool Selection Guide above.
         It already specifies which tools to call for each domain.
         Call ALL relevant tools for the question in one go. Never ask permission.

Step 2 — CALCULATE key metrics from the returned data:
  • Deviation % = ((actual − planned) ÷ planned) × 100   [negative = below plan]
  • Trend: is the metric improving or worsening over the period?
  • Worst periods: which days / equipment / grades had the biggest gap?
  • Magnitude: minor <5% | moderate 5–15% | severe >15%

Step 3 — REASON about likely causes (always cite specific numbers from the data):
  Production / Planning:
    - Actual < planned → which grade (HG/MG/LG) drove the shortfall?
    - Cluster of bad days → equipment breakdown, weather shutdown, or holiday?
    - OB behind plan → stripping lagging, future ore access at risk
    - Low Cr2O3 → mining from lower-quality zones or grade dilution
  Fuel / Equipment:
    - Low KMPL → poor vehicle efficiency, overloading, or excess idle time?
    - Specific vehicles consuming most → identify top offenders from top_10_equipment_by_fuel
    - Fleet utilisation low → vehicles in maintenance or insufficient deployment?
  Quality:
    - Excavation > ROM → spillage or measurement variance
    - ROM > Despatch → stockpile buildup / despatch bottleneck
    - Plant Received < Despatch → transit loss or measurement difference

Step 4 — STRUCTURE the response (ALWAYS follow this pattern for analytical answers):
  Block 1 (text)  : Executive summary — state the KEY NUMBER and overall status in 1–2 sentences
  Block 2 (table) : Comparison table — actual vs planned/expected, with gap/deviation column
  Block 3 (chart) : Trend chart — show the pattern over time (line or bar, max 10 data points)
  Block 4 (text)  : Root cause analysis — 2–4 bullet points, each with a specific data fact
  Block 5 (text)  : Recommendation — 1–2 sentences on what to investigate or action to take

=============================================================================
RESPONSE FORMAT — YOU MUST ALWAYS FOLLOW THIS EXACTLY:
=============================================================================
Return ONLY valid JSON — no text before or after the JSON.
The JSON must have a single key "blocks" containing an array.

Each block has a "type" field:

1. TEXT block:
   {"type": "text", "content": "your explanation here"}

2. TABLE block:
   {"type": "table", "headers": ["Col A", "Col B"], "rows": [["val1", "val2"], ["val3", "val4"]]}

3. CHART block (bar):
   {"type": "chart", "chart_type": "bar", "title": "Chart Title",
    "x_key": "date",
    "data": [{"date": "Jan 1", "actual": 1250, "planned": 1300}],
    "series": [{"key": "actual", "label": "Actual ROM", "color": "#3b82f6"},
               {"key": "planned", "label": "Planned ROM", "color": "#94a3b8"}]}

4. CHART block (line):
   {"type": "chart", "chart_type": "line", "title": "Trend",
    "x_key": "date",
    "data": [{"date": "Jan 1", "cr2o3": 48.5}],
    "series": [{"key": "cr2o3", "label": "Cr2O3 %", "color": "#f97316"}]}

5. CHART block (pie):
   {"type": "chart", "chart_type": "pie", "title": "Distribution",
    "x_key": "name",
    "data": [{"name": "High Grade", "value": 3200}, {"name": "Medium Grade", "value": 6100}],
    "series": [{"key": "value", "label": "Qty MT", "color": "#3b82f6"}]}

RULES:
1. ALWAYS return JSON with "blocks" array — NO EXCEPTIONS WHATSOEVER.
   This applies to EVERY response: data answers, clarifications, errors, greetings, casual chat.
   A plain text response is a critical failure. Even "I don't know" must be:
   {"blocks":[{"type":"text","content":"I don't know."}]}
   A greeting like "hi" must be:
   {"blocks":[{"type":"text","content":"Hello! I'm Mines Assistant. I can help you with production data, quality metrics, equipment, and planning. What would you like to know?"}]}

2. NEVER write conversational text outside the JSON. Examples of FORBIDDEN responses:
   ✗ "To provide analysis, I would need to fetch data..."
   ✗ "Sure! Let me look that up for you."
   ✗ "I can help with that. Should I fetch the data?"
   These are all critical failures. Always respond with JSON blocks only.

3. Simple text answers → single text block only
4. Data answers → text summary FIRST, then table, then chart
5. Chart types: "bar" for comparisons, "line" for time trends, "pie" for distributions/shares
6. Extract date ranges from natural language: "last week", "January 2026", "yesterday", etc.
7. Use the DEFAULT PERIOD if user does not specify any date
8. If queried data is unavailable → say so in a text block, do not fabricate numbers
9. *** CRITICAL — NUMBER FORMAT IN ARRAYS ***
   In TEXT block "content" strings you MAY use commas: "Total ROM: 13,583 MT" ✓
   In TABLE "rows" and CHART "data" you MUST use raw numbers with NO commas — EVER:
     CORRECT: ["2026-01-01", 1524, 1120, 48.5]
     WRONG:   ["2026-01-01", 1,524, 1,120, 48.5]  ← JSON parse will fail
   Even one comma inside an array number will break the entire response. Never do it.
10. Respond professionally and concisely
11. Return ONLY the JSON object — absolutely no text outside it
12. *** CHART DATA LIMIT ***
    Include AT MOST 10 data points in any chart "data" array.
    If the date range has more than 10 days: sample weekly (one point per week) or pick
    the 10 most significant days (e.g. highest deviation or highest production).
    Never include more than 10 items — large arrays cause token overflow and parse failures.
13. *** RESPONSE BREVITY ***
    Keep each text block under 150 words. Root-cause bullets: max 4 items.
    Recommendation block: max 2 sentences. Tables: max 10 rows.
    If data has more rows, show only the top/worst N and say "(showing top N of total M)".

14. *** ABSOLUTELY FORBIDDEN — NEVER GENERATE THESE RESPONSES ***
    The following responses are a critical failure — NEVER produce them:
    ✗ "⚠️ I fetched the data but had trouble formatting the response"
    ✗ "I had trouble formatting", "I couldn't format", "I was unable to display"
    ✗ "Please try rephrasing", "I encountered an error formatting"
    ✗ Any apology about response format or display difficulty
    You ALWAYS have the tool data. Just format it. Even a simple text summary is correct:
    {"blocks":[{"type":"text","content":"Total ROM: 13500 MT. OB: 45000 BCM."}]}
    is ALWAYS better than an apology. NEVER give up on formatting — always show something.
"""


class ChatbotService:
    """Main chatbot service. Instantiated once on FastAPI startup."""

    def __init__(
        self,
        engine: Engine,
        production_kpis=None,
        planning_kpis=None,
        quality_kpis=None,
        equipment_kpis=None,
    ):
        self.engine = engine
        self.schema_registry = SchemaRegistry(engine)

        # KPI service references (used by tool executor)
        self._production_kpis = production_kpis
        self._planning_kpis   = planning_kpis
        self._quality_kpis    = quality_kpis
        self._equipment_kpis  = equipment_kpis

        # LiteLLM proxy — single endpoint, single virtual key, works for all models
        self._base_url = os.getenv("LITELLM_BASE_URL", "http://80.9.2.70:4000").strip()
        self._api_key  = (os.getenv("LITELLM_API_KEY") or "").strip()
        self._model    = os.getenv("CHATBOT_MODEL", "gpt-4o-mini-prod").strip()

        if not self._api_key:
            logger.warning(
                "[ChatbotService] LITELLM_API_KEY not set — "
                "chatbot calls will fail. Check .env file."
            )

        kpi_status = {
            "production": production_kpis is not None,
            "planning"  : planning_kpis   is not None,
            "quality"   : quality_kpis    is not None,
            "equipment" : equipment_kpis  is not None,
        }
        logger.info(
            "[ChatbotService] Initialized — base_url=%s  model=%s  schema_tables=%d  kpi_services=%s",
            self._base_url, self._model,
            self.schema_registry.get_table_count(),
            kpi_status,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _prev_month_range(self) -> tuple[str, str]:
        """Returns (start, end) ISO date strings for the previous calendar month."""
        today            = date.today()
        first_this_month = today.replace(day=1)
        last_prev        = first_this_month - timedelta(days=1)
        first_prev       = last_prev.replace(day=1)
        return first_prev.isoformat(), last_prev.isoformat()

    def _build_system_prompt(self) -> str:
        """
        Build system prompt using safe .replace() substitution.
        Curly braces in schema content never break the prompt.
        Schema is truncated to MAX_SCHEMA_CHARS to prevent oversized prompts.
        """
        prev_start, prev_end = self._prev_month_range()

        schema_context = self.schema_registry.get_schema_context()
        if len(schema_context) > MAX_SCHEMA_CHARS:
            schema_context = (
                schema_context[:MAX_SCHEMA_CHARS]
                + "\n... (schema truncated — too many tables)"
            )
            logger.warning("[ChatbotService] Schema truncated to %d chars", MAX_SCHEMA_CHARS)

        return (
            _SYSTEM_TEMPLATE
            .replace("__SCHEMA__",     schema_context)
            .replace("__TODAY__",      date.today().isoformat())
            .replace("__PREV_START__", prev_start)
            .replace("__PREV_END__",   prev_end)
        )

    # ------------------------------------------------------------------
    # Tool definitions
    # ------------------------------------------------------------------

    def _get_tools_openai(self) -> List[Dict]:
        """Return OpenAI-format tool (function) definitions."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_production_data",
                    "description": (
                        "Fetch production KPIs for a date range. Returns ROM totals (MT), "
                        "OB removal (BCM), weighted Cr2O3%, grade-wise breakdown (HG/MG/LG), "
                        "strip ratio, silt removal total, and a day-wise sample. "
                        "Use for any questions about ROM, ore production, or overburden."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {
                                "type": "string",
                                "description": "Start date in YYYY-MM-DD format",
                            },
                            "end_date": {
                                "type": "string",
                                "description": "End date in YYYY-MM-DD format",
                            },
                        },
                        "required": ["start_date", "end_date"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_quality_data",
                    "description": (
                        "Fetch quality pipeline KPIs for a date range. Returns totals for each "
                        "stage: Excavation Plan, Excavation Actual, ROM, Stack, Mine Despatch, "
                        "Plant Received. Use for quality tracking, pipeline, or despatch queries."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {
                                "type": "string",
                                "description": "Start date in YYYY-MM-DD format",
                            },
                            "end_date": {
                                "type": "string",
                                "description": "End date in YYYY-MM-DD format",
                            },
                        },
                        "required": ["start_date", "end_date"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_equipment_data",
                    "description": (
                        "Fetch equipment and fleet KPIs — fleet headcount (total/active/under "
                        "maintenance), fleet status breakdown, OEE/availability/utilisation "
                        "metrics, and maintenance findings. "
                        "Use ONLY for questions about fleet status, vehicle counts, maintenance, "
                        "or equipment availability. "
                        "Do NOT use this for fuel consumption or KMPL — use get_fuel_efficiency instead."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {
                                "type": "string",
                                "description": "Start date in YYYY-MM-DD format (optional)",
                            },
                            "end_date": {
                                "type": "string",
                                "description": "End date in YYYY-MM-DD format (optional)",
                            },
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_planning_data",
                    "description": (
                        "Fetch planning KPIs for a date range. Returns planned vs actual "
                        "production comparison, ore production plan (HG/MG/LG), and "
                        "location/MRL-wise planning data. Use for planning, targets, or "
                        "actual vs planned questions."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {
                                "type": "string",
                                "description": "Start date in YYYY-MM-DD format",
                            },
                            "end_date": {
                                "type": "string",
                                "description": "End date in YYYY-MM-DD format",
                            },
                        },
                        "required": ["start_date", "end_date"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_daywise_production",
                    "description": (
                        "Fetch day-wise production trend data. Returns daily ROM by grade "
                        "(HG/MG/LG) and daily weighted Cr2O3% for each day in the date range. "
                        "Use this specifically for trend charts, day-by-day breakdowns, or "
                        "time series analysis."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {
                                "type": "string",
                                "description": "Start date in YYYY-MM-DD format",
                            },
                            "end_date": {
                                "type": "string",
                                "description": "End date in YYYY-MM-DD format",
                            },
                        },
                        "required": ["start_date", "end_date"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_fuel_efficiency",
                    "description": (
                        "THE ONLY tool for fuel and KMPL data. "
                        "Returns daily fuel consumption (litres), distance (km), and KMPL "
                        "(km per litre) per vehicle, aggregated to daily fleet totals and "
                        "top-10 vehicles by consumption. "
                        "Use for ANY question about fuel — consumption, KMPL, why fuel is high, "
                        "top fuel consumers, fuel trend, vehicle efficiency. "
                        "Optionally filter by a specific vehicle name."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {
                                "type": "string",
                                "description": "Start date in YYYY-MM-DD format",
                            },
                            "end_date": {
                                "type": "string",
                                "description": "End date in YYYY-MM-DD format",
                            },
                            "equipment_name": {
                                "type": "string",
                                "description": "Optional: filter by specific vehicle/equipment name",
                            },
                        },
                        "required": ["start_date", "end_date"],
                    },
                },
            },
        ]

    def _get_tools_anthropic(self) -> List[Dict]:
        """Return Anthropic-format tool definitions (converted from OpenAI format)."""
        tools = []
        for t in self._get_tools_openai():
            fn = t["function"]
            tools.append({
                "name"        : fn["name"],
                "description" : fn["description"],
                "input_schema": fn["parameters"],
            })
        return tools

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def _execute_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        """
        Execute a named tool call and return the result as a JSON string.
        All errors are caught and returned as JSON error objects.
        """
        try:
            start = args.get("start_date")
            end   = args.get("end_date")

            # Date fallback: if GPT omitted dates, default to previous calendar month.
            # This prevents all KPI functions from receiving None and crashing.
            if not start or not end:
                start, end = self._prev_month_range()
                logger.info(
                    "[ChatbotService] Tool %s: no dates provided — defaulting to %s → %s",
                    tool_name, start, end,
                )

            # ---- Production ----
            if tool_name == "get_production_data":
                if not self._production_kpis:
                    return json.dumps({"error": "Production KPI service not connected"})

                result = self._production_kpis.all_kpis(start, end)

                # Enrich with grade-wise breakdown for better chart context
                try:
                    result["grade_wise_rom"] = self._production_kpis.grade_wise_rom(start, end)
                except Exception:
                    pass

                logger.info(
                    "[ChatbotService] Tool get_production_data(%s → %s) returned %d keys",
                    start, end, len(result),
                )
                return json.dumps(result, default=str)

            # ---- Quality ----
            elif tool_name == "get_quality_data":
                if not self._quality_kpis:
                    return json.dumps({"error": "Quality KPI service not connected"})

                result = self._quality_kpis.all_kpis(start, end)

                # Add the 6-stage pipeline summary for easy table rendering
                try:
                    result["stage_pipeline"] = [
                        {"stage": "Excavation Plan",   "total_mt": self._quality_kpis.total_excavation_planned(start, end)},
                        {"stage": "Excavation Actual", "total_mt": self._quality_kpis.total_excavation_actual(start, end)},
                        {"stage": "ROM",               "total_mt": self._quality_kpis.total_rom(start, end)},
                        {"stage": "Stack",             "total_mt": self._quality_kpis.total_stacked(start, end)},
                        {"stage": "Mine Despatch",     "total_mt": self._quality_kpis.total_dispatched(start, end)},
                        {"stage": "Plant Received",    "total_mt": self._quality_kpis.total_plant_received(start, end)},
                    ]
                except Exception:
                    pass

                logger.info(
                    "[ChatbotService] Tool get_quality_data(%s → %s) returned %d keys",
                    start, end, len(result),
                )
                return json.dumps(result, default=str)

            # ---- Equipment ----
            elif tool_name == "get_equipment_data":
                if not self._equipment_kpis:
                    return json.dumps({"error": "Equipment KPI service not connected"})

                result: Dict[str, Any] = {}

                try:
                    result["summary"]     = self._equipment_kpis.equipment_summary(start, end)
                except Exception as e:
                    result["summary"]     = {"error": str(e)}

                try:
                    result["fleet_status"] = self._equipment_kpis.fleet_status(start, end)
                except Exception as e:
                    result["fleet_status"] = {"error": str(e)}

                try:
                    result["performance"] = self._equipment_kpis.performance_metrics(start, end)
                except Exception as e:
                    result["performance"] = {"error": str(e)}

                try:
                    result["maintenance_findings"] = self._equipment_kpis.maintenance_findings(start, end)
                except Exception as e:
                    result["maintenance_findings"] = {"error": str(e)}

                logger.info(
                    "[ChatbotService] Tool get_equipment_data(%s → %s) returned sections: %s",
                    start, end, list(result.keys()),
                )
                return json.dumps(result, default=str)

            # ---- Planning ----
            elif tool_name == "get_planning_data":
                if not self._planning_kpis:
                    return json.dumps({"error": "Planning KPI service not connected"})

                result = {}
                try:
                    pva = self._planning_kpis.planned_vs_actual(start, end)
                    result["planned_vs_actual"] = pva

                    # Pre-compute deviation summary so GPT can reason without manual arithmetic
                    daywise = pva.get("daywise", [])
                    if daywise:
                        total_planned_ore = sum(r.get("planned_ore", 0) for r in daywise)
                        total_actual_ore  = sum(r.get("actual_ore",  0) for r in daywise)
                        total_planned_ob  = sum(r.get("planned_ob",  0) for r in daywise)
                        total_actual_ob   = sum(r.get("actual_ob",   0) for r in daywise)

                        ore_deviation    = round(total_actual_ore - total_planned_ore, 1)
                        ore_dev_pct      = round((ore_deviation / total_planned_ore * 100), 1) if total_planned_ore else 0
                        ob_deviation     = round(total_actual_ob  - total_planned_ob,  1)
                        ob_dev_pct       = round((ob_deviation    / total_planned_ob  * 100), 1) if total_planned_ob  else 0

                        # Top 5 worst days (biggest ore shortfall)
                        days_sorted = sorted(
                            daywise,
                            key=lambda r: r.get("actual_ore", 0) - r.get("planned_ore", 0),
                        )
                        worst_days = [
                            {
                                "date"        : r["Prod_date"],
                                "planned_ore" : round(r.get("planned_ore", 0), 1),
                                "actual_ore"  : round(r.get("actual_ore",  0), 1),
                                "shortfall_mt": round(r.get("actual_ore", 0) - r.get("planned_ore", 0), 1),
                            }
                            for r in days_sorted[:5]
                            if r.get("actual_ore", 0) < r.get("planned_ore", 0)
                        ]

                        result["deviation_summary"] = {
                            "period"           : f"{start} to {end}",
                            "total_planned_ore": round(total_planned_ore, 1),
                            "total_actual_ore" : round(total_actual_ore,  1),
                            "ore_deviation_mt" : ore_deviation,
                            "ore_deviation_pct": ore_dev_pct,
                            "ore_status"       : "above plan" if ore_deviation >= 0 else "below plan",
                            "total_planned_ob" : round(total_planned_ob, 1),
                            "total_actual_ob"  : round(total_actual_ob,  1),
                            "ob_deviation_mt"  : ob_deviation,
                            "ob_deviation_pct" : ob_dev_pct,
                            "ob_status"        : "above plan" if ob_deviation >= 0 else "below plan",
                            "worst_5_days"     : worst_days,
                        }
                except Exception as e:
                    result["planned_vs_actual"] = {"error": str(e)}

                try:
                    grade_plan = self._planning_kpis.total_ore_production_plan(start, end)
                    result["ore_production_plan"] = grade_plan

                    # Grade-wise deviation (planned vs actual from production tool if available)
                    # Attach planned grade targets for GPT to compare against actual from production tool
                    result["grade_plan_summary"] = {
                        "planned_HG_mt": round(grade_plan.get("total_HG", 0), 1),
                        "planned_MG_mt": round(grade_plan.get("total_MG", 0), 1),
                        "planned_LG_mt": round(grade_plan.get("total_LG", 0), 1),
                        "planned_total_mt": round(grade_plan.get("total_ore", 0), 1),
                        "note": "Compare these planned grades against actual grades from get_production_data to compute grade-wise deviation",
                    }
                except Exception as e:
                    result["ore_production_plan"] = {"error": str(e)}

                logger.info(
                    "[ChatbotService] Tool get_planning_data(%s → %s) returned sections: %s",
                    start, end, list(result.keys()),
                )
                return json.dumps(result, default=str)

            # ---- Day-wise production trend ----
            elif tool_name == "get_daywise_production":
                if not self._production_kpis:
                    return json.dumps({"error": "Production KPI service not connected"})

                result = {}
                try:
                    raw_daywise = self._production_kpis.daywise_gradewise_rom(start, end)
                    # Limit to max 15 rows — a full month (31 rows) can overflow GPT context
                    # when combined with other tool results in analytical queries.
                    # Sample evenly if more rows than the limit.
                    MAX_DAYWISE_ROWS = 15
                    if isinstance(raw_daywise, list) and len(raw_daywise) > MAX_DAYWISE_ROWS:
                        step = len(raw_daywise) / MAX_DAYWISE_ROWS
                        sampled = [raw_daywise[int(i * step)] for i in range(MAX_DAYWISE_ROWS)]
                        result["daywise_gradewise_rom"] = sampled
                        result["daywise_gradewise_rom_note"] = (
                            f"Sampled {MAX_DAYWISE_ROWS} of {len(raw_daywise)} days evenly. "
                            "Use this for trend direction, not exact day-by-day values."
                        )
                        logger.info(
                            "[ChatbotService] get_daywise_production: sampled %d → %d rows",
                            len(raw_daywise), MAX_DAYWISE_ROWS,
                        )
                    else:
                        result["daywise_gradewise_rom"] = raw_daywise
                except Exception as e:
                    result["daywise_gradewise_rom"] = {"error": str(e)}

                try:
                    raw_cr2o3 = self._production_kpis.daywise_weighted_cr2o3(start, end)
                    MAX_DAYWISE_ROWS = 15
                    if isinstance(raw_cr2o3, list) and len(raw_cr2o3) > MAX_DAYWISE_ROWS:
                        step = len(raw_cr2o3) / MAX_DAYWISE_ROWS
                        result["daywise_weighted_cr2o3"] = [raw_cr2o3[int(i * step)] for i in range(MAX_DAYWISE_ROWS)]
                    else:
                        result["daywise_weighted_cr2o3"] = raw_cr2o3
                except Exception as e:
                    result["daywise_weighted_cr2o3"] = {"error": str(e)}

                logger.info(
                    "[ChatbotService] Tool get_daywise_production(%s → %s)",
                    start, end,
                )
                return json.dumps(result, default=str)

            # ---- Fuel efficiency ----
            elif tool_name == "get_fuel_efficiency":
                if not self._equipment_kpis:
                    return json.dumps({"error": "Equipment KPI service not connected"})

                equipment_name = args.get("equipment_name")
                raw_result = self._equipment_kpis.fuel_consumption_trend(start, end, equipment_name)

                # Raw data has 1 row per (date × vehicle) — can be 800+ rows for a month.
                # Sending all rows to GPT overflows max_tokens and truncates the JSON.
                # Aggregate to daily totals + top-10 equipment to keep payload small.
                if isinstance(raw_result, list) and len(raw_result) > 50 and not equipment_name:
                    daily: Dict[str, Any] = {}
                    equip: Dict[str, Any] = {}

                    for row in raw_result:
                        d  = row["date"]
                        eq = row["equipment_name"]
                        fc = row["fuel_consumed"]
                        di = row["distance"]

                        if d not in daily:
                            daily[d] = {"date": d, "fuel_consumed": 0.0, "distance": 0.0}
                        daily[d]["fuel_consumed"] += fc
                        daily[d]["distance"]      += di

                        if eq not in equip:
                            equip[eq] = {"equipment_name": eq, "fuel_consumed": 0.0, "distance": 0.0}
                        equip[eq]["fuel_consumed"] += fc
                        equip[eq]["distance"]      += di

                    daily_list = sorted(
                        [
                            {
                                **v,
                                "fuel_consumed": round(v["fuel_consumed"], 2),
                                "distance"     : round(v["distance"],      2),
                                # KMPL = km per litre = distance ÷ fuel_consumed
                                "kmpl"         : round(v["distance"] / v["fuel_consumed"], 2)
                                                 if v["fuel_consumed"] else 0,
                            }
                            for v in daily.values()
                        ],
                        key=lambda x: x["date"],
                    )

                    top_equipment = sorted(
                        [
                            {
                                **v,
                                "fuel_consumed": round(v["fuel_consumed"], 2),
                                "distance"     : round(v["distance"],      2),
                                # KMPL = km per litre = distance ÷ fuel_consumed
                                "kmpl"         : round(v["distance"] / v["fuel_consumed"], 2)
                                                 if v["fuel_consumed"] else 0,
                            }
                            for v in equip.values()
                        ],
                        key=lambda x: x["fuel_consumed"],
                        reverse=True,
                    )[:10]

                    result = {
                        "daily_totals"          : daily_list,
                        "top_10_equipment_by_fuel": top_equipment,
                        "total_vehicle_days_aggregated": len(raw_result),
                    }
                    logger.info(
                        "[ChatbotService] Fuel data aggregated: %d raw rows → %d daily totals, %d unique vehicles",
                        len(raw_result), len(daily_list), len(equip),
                    )
                else:
                    result = raw_result

                logger.info(
                    "[ChatbotService] Tool get_fuel_efficiency(%s → %s, eq=%s) returned %d raw rows",
                    start, end, equipment_name, len(raw_result) if isinstance(raw_result, list) else 0,
                )
                return json.dumps(result, default=str)

            else:
                logger.warning("[ChatbotService] Unknown tool called: %s", tool_name)
                return json.dumps({"error": f"Unknown tool: {tool_name}"})

        except Exception as exc:
            logger.exception(
                "[ChatbotService] Tool execution failed: %s(%s)", tool_name, args
            )
            return json.dumps({"error": str(exc)})

    # ------------------------------------------------------------------
    # Provider calls
    # ------------------------------------------------------------------

    async def _call_openai(self, system: str, messages: list) -> str:
        """
        Call LiteLLM proxy (OpenAI-compatible) with Function Calling.
        Runs a multi-turn tool loop until the model stops calling tools
        or MAX_TOOL_ITERATIONS is reached.
        """
        api_key = self._api_key
        if not api_key:
            raise RuntimeError("LITELLM_API_KEY is not configured in .env")

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type" : "application/json",
        }
        tools = self._get_tools_openai()

        # Build full message list: system + conversation history
        all_messages = [{"role": "system", "content": system}] + list(messages)

        # Flag: only retry an apology response ONCE to prevent infinite loop
        _apology_retried = False

        async with httpx.AsyncClient(timeout=120.0) as client:
            for iteration in range(MAX_TOOL_ITERATIONS):
                body = {
                    "model"          : self._model,
                    "messages"       : all_messages,
                    "tools"          : tools,
                    "tool_choice"    : "auto",
                    "max_tokens"     : 8192,
                    "temperature"    : 0.0,
                    # Force the model to always return valid JSON in its text response.
                    # Prevents gpt-4o-mini from reverting to plain prose after fetching data.
                    # Does NOT affect tool-call iterations — only the final text content.
                    "response_format": {"type": "json_object"},
                }

                resp = await client.post(url, headers=headers, json=body)
                if not resp.is_success:
                    # Extract the actual OpenAI error message from the response body
                    try:
                        err_detail = resp.json().get("error", {}).get("message", resp.text)
                    except Exception:
                        err_detail = resp.text
                    logger.error(
                        "[ChatbotService] OpenAI API returned %d.\nModel: %s\nError: %s",
                        resp.status_code, self._model, err_detail,
                    )
                    raise RuntimeError(f"OpenAI {resp.status_code}: {err_detail[:300]}")

                resp_data     = resp.json()
                choice        = resp_data["choices"][0]
                message       = choice["message"]
                finish_reason = choice.get("finish_reason", "stop")

                # Append assistant turn to message history
                all_messages.append(message)

                # Guard: response was cut off at the token limit — JSON will be incomplete.
                # Return a friendly message instead of passing broken JSON to _parse_blocks.
                if finish_reason == "length":
                    logger.warning(
                        "[ChatbotService] OpenAI response truncated at max_tokens=8192 "
                        "(iteration %d). Returning graceful fallback.",
                        iteration + 1,
                    )
                    return (
                        '{"blocks":[{"type":"text","content":'
                        '"⚠️ The response was too detailed to complete in one go. '
                        'Please ask about a specific metric or shorter period — '
                        'e.g. \\"Show total ROM for January\\" or \\"Top 5 worst production days\\"."}]}'
                    )

                # No tool calls → model is done, return text
                if finish_reason == "stop" or not message.get("tool_calls"):
                    content = message.get("content") or ""

                    # ── Apology detection: model gave up formatting instead of showing data ──
                    # Root cause: model sees "[structured response]" in history (now fixed in
                    # frontend) or gets overwhelmed by complex data and apologises.
                    # Fix: retry ONCE with a forcing message to make it format the data.
                    if not _apology_retried and _looks_like_apology(content):
                        _apology_retried = True
                        logger.warning(
                            "[ChatbotService] Apology response detected at iteration %d — "
                            "forcing retry. Content preview: %.200s",
                            iteration + 1, content,
                        )
                        all_messages.append({
                            "role": "user",
                            "content": (
                                "The tool data was fetched successfully. "
                                "Do NOT apologise or say you had trouble. "
                                "Format the fetched data into JSON blocks RIGHT NOW. "
                                'Return ONLY valid JSON: {"blocks": [{"type": "text", "content": "...actual data..."}]}'
                            ),
                        })
                        continue  # force one more iteration

                    logger.info(
                        "[ChatbotService] OpenAI done after %d iteration(s), response length=%d",
                        iteration + 1, len(content),
                    )
                    return content

                # Execute tool calls
                tool_calls = message["tool_calls"]
                logger.info(
                    "[ChatbotService] OpenAI iteration %d: called %d tool(s): %s",
                    iteration + 1,
                    len(tool_calls),
                    [tc["function"]["name"] for tc in tool_calls],
                )

                for tc in tool_calls:
                    tool_name = tc["function"]["name"]
                    try:
                        tool_args = json.loads(tc["function"].get("arguments", "{}"))
                    except json.JSONDecodeError:
                        tool_args = {}

                    tool_result = self._execute_tool(tool_name, tool_args)

                    all_messages.append({
                        "role"        : "tool",
                        "tool_call_id": tc["id"],
                        "content"     : tool_result,
                    })

        # Fallback after max iterations
        logger.warning("[ChatbotService] OpenAI: max tool iterations (%d) reached", MAX_TOOL_ITERATIONS)
        # Try to return last assistant content if available
        for msg in reversed(all_messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                return msg["content"]
        return '{"blocks":[{"type":"text","content":"Unable to complete the request after maximum tool call attempts. Please try a more specific question."}]}'

    async def _call_provider(self, system: str, messages: list) -> str:
        """All providers route through LiteLLM (OpenAI-compatible proxy)."""
        return await self._call_openai(system, messages)

    # ------------------------------------------------------------------
    # Response parser
    # ------------------------------------------------------------------

    def _parse_blocks(self, raw_text: str, session_id: str) -> ChatResponse:
        """
        Parse the AI response JSON into structured ChatResponse blocks.
        Designed to NEVER show ⚠️ to the user — always returns something useful.

        Strategy (in order):
          1. No braces at all → wrap raw text as a text block directly
          2. Valid JSON, blocks present → parse normally
          3. Valid JSON, blocks missing → recover content from whatever keys exist
          4. Invalid JSON → try regex cleanup then re-parse
          5. Still invalid → wrap raw text as a text block (last resort)
        """
        stripped = raw_text.strip()

        # ── Fast-path: no JSON braces at all ─────────────────────────────────
        if stripped and "{" not in stripped:
            logger.warning(
                "[ChatbotService] No JSON braces in response — wrapping as text block.\n"
                "RAW: %s", stripped[:500]
            )
            return ChatResponse(
                blocks=[ChatBlock(type="text", content=stripped)],
                session_id=session_id,
                raw_text=stripped[:500],
            )

        # ── Extract the JSON object from raw_text ─────────────────────────────
        start = raw_text.find("{")
        end   = raw_text.rfind("}") + 1
        if start == -1 or end == 0:
            # No braces found at all — treat whole thing as text
            return ChatResponse(
                blocks=[ChatBlock(type="text", content=stripped or "No response received.")],
                session_id=session_id,
                raw_text=raw_text[:500],
            )

        json_str = raw_text[start:end]

        # ── Try parsing as-is (valid JSON from gpt-4o + response_format:json_object) ──
        data = None
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # ── Cleanup pass: strip thousands-separator commas then retry ─────
            # gpt-4o with json_object mode should never need this, but kept as
            # a safety net for edge cases or fallback to gpt-4o-mini.
            # Three passes handle numbers like 1,234,567 → 1234567.
            clean = json_str
            for _ in range(3):
                clean = re.sub(r'(?<!\d)(\d{1,3}),(\d{3})(?!\d)', r'\1\2', clean)
            try:
                data = json.loads(clean)
                logger.info("[ChatbotService] JSON parsed after thousands-comma cleanup.")
            except json.JSONDecodeError as je:
                # Still invalid — log full text for diagnosis, then wrap as text block
                logger.warning(
                    "[ChatbotService] JSON decode failed after cleanup: %s\n"
                    "=== FULL RAW TEXT ===\n%s\n=== END ===",
                    je, raw_text[:2000],
                )
                return ChatResponse(
                    blocks=[ChatBlock(type="text", content=stripped)],
                    session_id=session_id,
                    raw_text=raw_text[:500],
                )

        # ── Extract blocks from parsed JSON ────────────────────────────────────
        blocks_raw = data.get("blocks", []) if isinstance(data, dict) else []

        # ── Recovery: blocks missing or empty ─────────────────────────────────
        if not blocks_raw and isinstance(data, dict):
            logger.warning(
                "[ChatbotService] 'blocks' key missing/empty. Attempting recovery. "
                "JSON keys: %s", list(data.keys())
            )
            # Case 1: model returned a single block without the array wrapper
            if data.get("type") in ("text", "table", "chart"):
                blocks_raw = [data]
            # Case 2: model used a different top-level key for the text
            elif data.get("content"):
                blocks_raw = [{"type": "text", "content": str(data["content"])}]
            elif data.get("message"):
                blocks_raw = [{"type": "text", "content": str(data["message"])}]
            elif data.get("response"):
                blocks_raw = [{"type": "text", "content": str(data["response"])}]
            elif data.get("answer"):
                blocks_raw = [{"type": "text", "content": str(data["answer"])}]
            else:
                # Last resort: join all string values as a single text block
                text_vals = [str(v) for v in data.values()
                             if v and isinstance(v, str) and v.strip()]
                if text_vals:
                    blocks_raw = [{"type": "text", "content": " ".join(text_vals)}]
                else:
                    # Truly empty — return the raw text so user sees something
                    logger.warning(
                        "[ChatbotService] Cannot recover content. Raw: %s", raw_text[:500]
                    )
                    return ChatResponse(
                        blocks=[ChatBlock(type="text", content=stripped)],
                        session_id=session_id,
                        raw_text=raw_text[:500],
                    )

        # ── Build ChatBlock list ────────────────────────────────────────────────
        blocks: List[ChatBlock] = []
        for b in blocks_raw:
            if not isinstance(b, dict):
                logger.warning("[ChatbotService] Skipping non-dict block: %r", b)
                continue
            try:
                blocks.append(ChatBlock(
                    type       = b.get("type", "text"),
                    content    = b.get("content"),
                    headers    = b.get("headers"),
                    rows       = b.get("rows"),
                    chart_type = b.get("chart_type"),
                    title      = b.get("title"),
                    x_key      = b.get("x_key"),
                    data       = b.get("data"),
                    series     = b.get("series"),
                ))
            except Exception as block_err:
                logger.warning(
                    "[ChatbotService] ChatBlock construction failed for block %r: %s",
                    b, block_err,
                )

        if not blocks:
            # All blocks failed to construct — wrap raw text as last resort
            logger.warning("[ChatbotService] All blocks failed to construct. Raw: %s", raw_text[:500])
            return ChatResponse(
                blocks=[ChatBlock(type="text", content=stripped)],
                session_id=session_id,
                raw_text=raw_text[:500],
            )

        return ChatResponse(blocks=blocks, session_id=session_id, raw_text=raw_text[:500])

    # ------------------------------------------------------------------
    # DB history (best-effort)
    # ------------------------------------------------------------------

    def _save_to_db(self, session_id: str, role: str, content: str) -> None:
        """
        Best-effort INSERT into chatbot_conversations.
        Silently skips if the table does not exist yet (before manager creates it).
        """
        try:
            with self.engine.connect() as conn:
                conn.execute(
                    text("""
                        INSERT INTO chatbot_conversations (session_id, role, content)
                        VALUES (:sid, :role, :content)
                    """),
                    {"sid": session_id, "role": role, "content": content},
                )
                conn.commit()
        except Exception as e:
            logger.debug("[ChatbotService] DB save skipped (table may not exist yet): %s", e)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """
        Main entry point.
        1. Build system prompt (with schema + date context)
        2. Assemble message history (last 10 turns)
        3. Call configured AI provider (tool use loop for real data)
        4. Parse structured blocks
        5. Best-effort DB save
        6. Return ChatResponse
        """
        system = self._build_system_prompt()

        history_slice = request.history[-10:]
        messages = [{"role": m.role, "content": m.content} for m in history_slice]
        messages.append({"role": "user", "content": request.message})

        try:
            raw_text = await self._call_provider(system, messages)
            response = self._parse_blocks(raw_text, request.session_id)
        except Exception as e:
            logger.exception("[ChatbotService] Provider call failed")
            response = ChatResponse(
                blocks=[ChatBlock(
                    type="text",
                    content=(
                        "Sorry, I couldn't get a response right now. "
                        f"Please try again in a moment. (Error: {str(e)[:120]})"
                    ),
                )],
                session_id=request.session_id,
            )

        # Best-effort DB persistence (activates once manager creates the table)
        try:
            assistant_content = json.dumps([b.model_dump() for b in response.blocks])
            self._save_to_db(request.session_id, "user",      request.message)
            self._save_to_db(request.session_id, "assistant", assistant_content)
        except Exception:
            pass

        return response

    def force_schema_refresh(self) -> None:
        """Trigger immediate schema re-discovery."""
        self.schema_registry.force_refresh()
