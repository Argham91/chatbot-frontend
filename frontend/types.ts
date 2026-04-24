
// --- Global Types ---
export type DatePreset = 'thisMonth' | 'thisWeek' | 'prevMonth' | 'prevFinancialYear' | 'currentFinancialYear' | 'custom';

export interface DateRange {
  startDate: Date;
  endDate: Date;
  preset: DatePreset;
}

export interface DateContextType {
  dateRange: DateRange;
  setDateRange: (range: DateRange) => void;
  setPreset: (preset: DatePreset) => void;
}

// --- SYNOPSIS TYPES ---

export interface SynopsisMetric {
  name:            string;
  uom:             string;
  plan:            number | null;
  actual:          number;
  achievement_pct: number | null;
  variance:        number | null;
  is_header?:      boolean;
  is_sub_row?:     boolean;
}

export interface SynopsisPeriod {
  period:  string;
  start:   string;
  end:     string;
  metrics: SynopsisMetric[];
}

export interface SynopsisDespatchGroup {
  by_grade:       SynopsisMetric[];
  by_destination: SynopsisMetric[];
}

export interface SynopsisResponse {
  as_of_date:  string;
  td_date:     string;
  month_start: string;
  td:          SynopsisPeriod;
  mtd:         SynopsisPeriod;
  despatch: {
    td:  SynopsisDespatchGroup;
    mtd: SynopsisDespatchGroup;
  };
  cob: {
    td:  SynopsisMetric[];
    mtd: SynopsisMetric[];
  };
}

// --- API RAW RESPONSES (Backend Contract) ---

export interface RomTotalResponse {
  rom_total_Mt: number;
}

export interface WeightedAvgCr2O3Response {
  weighted_avg_cr2o3: number;
}

export interface SiltTotalResponse {
  silt_total_cum: number;
}

export type GradeWiseRomRawResponse = Record<string, { qty_Mt: number }>;

export interface DayWiseGradeRawItem {
  Prod_date: string;
  grade: string;
  qty_Mt: number;
}

export interface DayWiseCr2O3RawItem {
  Prod_date: string;
  weighted_cr2o3_pct: number;
  total_qty_Mt: number;
}

export interface DayWiseGradeCr2O3RawItem {
  Prod_date: string;
  grade: string;
  weighted_cr2o3_pct: number;
}

export interface LocationDayWiseRawItem {
  Prod_date: string;
  Loc_Id: number;
  Loc_Desc: string;
  rom_Mt: number;
  ob_cum: number;
}

export interface LocationSummaryRawItem {
  Loc_Id: number;
  Loc_Desc: string;
  rom_Mt: number;
  ob_cum: number;
}

// Planning Raw
export interface TotalOrePlanResponse {
  total_HG: number;
  total_MG: number;
  total_LG: number;
  total_ore: number;
}

export interface TotalObPlanResponse {
  total_ob_plan_cum: number;
}

export interface TotalLocationOreObRawItem {
  Loc_Id: number;
  Loc_Desc: string;
  total_ore: number;
  total_ob: number;
}

export interface PlannedVsActualRawResponse {
  daywise: Array<{
    Prod_date: string;
    planned_ore: number;
    actual_ore: number;
    planned_ob: number;
    actual_ob: number;
  }>;
}

export interface MrlPlanRawItem {
  Loc_Id: number;
  Loc_Desc: string;
  Z_Range: string;
  planned_ore: number;
  planned_ob: number;
}

// --- QUALITY RAW TYPES ---

export interface QualityKpiResponse {
  start_date: string;
  end_date: string;
  total_excavation_planned: number;
  total_excavation_actual: number;
  total_rom: number;
  total_stacked: number;
  total_dispatched: number;
  total_plant_received: number;
  average_quality: number | "Not Available";
  pct_quality_missing: number;
}

export interface QualityStageTotalItem {
  stage: string;
  total_quantity: number;
  average_quality: number | "Not Available";
}

export interface QualityDatewiseItem {
  date: string;
  excavation_plan: number;
  excavation_actual: number;
  rom: number;
  stacked: number;
  dispatched: number;
  plant_received: number;
  average_quality: number | "Not Available";
}

export interface QualityAreaItem {
  area: string;
  total_quantity: number;
  average_quality: number | "Not Available";
  missing_quality_rows: number;
}

export interface QualityStageEntry {
  material_desc: string | null;
  quantity: number | null;
  quality: number | null;
}

export interface QualityRawStage {
  area: string;
  entries: QualityStageEntry[]; // multiple material entries per stage per date
}

export interface QualityRawSummary {
  excavation_plan_qty:   number | null;
  excavation_actual_qty: number | null;
  rom_qty:               number | null;
  stack_qty:             number | null;
  despatch_qty:          number | null;
  received_qty:          number | null;
}

export interface QualityRawItem {
  prod_date: string;
  summary: QualityRawSummary;
  stages: QualityRawStage[];
}

// Legacy types support (if needed for migration, otherwise can be removed if unused)
export interface QualityFlowItem {
  stage: string;
  quantity: number;
  quality: number | "Not Available";
}
export interface QualityTimeSeriesItem {
  prod_date: string; 
  quantity: number;
  quality: number | "Not Available";
}
export interface QualityAllResponse {
  start_date: string;
  end_date: string;
  total_quantity: number;
  average_quality: number | "Not Available";
  pct_quality_missing: number;
  flow_summary: QualityFlowItem[];
  area_wise_quality: QualityAreaItem[];
  daywise_quality: QualityTimeSeriesItem[];
}

// --- NEW PLANNING TYPES ---

export interface PlanningLocation {
  Loc_Id: number;
  Loc_Desc: string;
}

export interface PlanningCapabilities {
  has_monthly_table: boolean;
  has_daily_table: boolean;
  has_location_master: boolean;
  monthly_has_cr2o3: boolean;
  monthly_has_crfe: boolean;
  daily_has_cr2o3: boolean;
  daily_has_grades: boolean;
  notes: string[];
}

export interface IntegratedPlanningItem {
  Loc_Id: number;
  Loc_Desc: string;
  Z_Range: string;
  planned_ore: number;
  planned_ob: number;
  total_HG: number;
  total_MG: number;
  total_LG: number;
  total_ore: number;
  weighted_Cr2O3: number;
  weighted_CrFe: number;
  strip_ratio: number;
}

export interface ChemistryItem {
  Loc_Id: number;
  Loc_Desc: string;
  Z_Range: string;
  weighted_Cr2O3: number | null;
  weighted_CrFe: number | null;
}

export interface DayWeekCuttingPlanResponse {
  daywise: Array<{ Prod_date: string; Z_Range: string | null; ore: number; ob: number }>;
  weekwise: Array<{ yearweek: string; ore: number; ob: number }>;
  mrl_monthly: Array<{ Z_Range: string; ore: number; ob: number }>;
}

// --- INSIGHTS API TYPES ---

export interface Insight {
  id: string;
  type: string;
  severity: 'low' | 'medium' | 'high';
  title: string;
  summary: string;
  confidence?: number | null;
  kpi_references: string[];
  detail?: string | null;
  suggested_actions: string[];
  metadata?: Record<string, any>;
}

export interface InsightsResponse {
  kpi_range: { start_date: string; end_date: string };
  provider: string;
  generated_at: string;
  insights: Insight[];
}

// --- UI TRANSFORMED MODELS (Frontend Consumption) ---

export interface ProductionKPIs {
  romTotal: number;
  avgCr2o3: number;
  obTotal: number;
  strippingRatio: number;
  siltRemoval: number;
}

export interface PlanningKPIs {
  totalPlannedOre: number;
  plannedHg: number;
  plannedMg: number;
  plannedLg: number;
  totalPlannedOb: number;
}

// Charts
export interface GradeWiseRomData {
  grade: string;
  tonnage: number;
}

export interface DayWiseGradeRomData {
  date: string;
  hg: number;
  mg: number;
  lg: number;
  total: number;
}

export interface DayWiseCr2O3Data {
  date: string;
  cr2o3: number;
}

export interface DayWiseGradeCr2O3Data {
  date: string;
  high: number;
  medium: number;
  low: number;
}

export interface LocationSummaryData {
  id: number;
  location_name: string;
  rom_tonnage: number;
  ob_volume: number;
  stripping_ratio: number;
}

export interface LocationDayWiseData {
  date: string;
  rom: number;
  ob: number;
}

export interface PlannedVsActualData {
  date: string;
  planned: number;
  actual: number;
}

export interface MrlPlanningData {
  mrl: string;
  planned_ore: number;
  planned_ob: number;
}

export interface InsightData {
  type: string;
  message: string;
  severity: 'good' | 'warning' | 'critical';
}

// ==========================================
// CHATBOT TYPES
// ==========================================

/** A single renderable block inside a chat message (text / table / chart). */
export interface ChatBlock {
  type: 'text' | 'table' | 'chart';
  // text block
  content?: string;
  // table block
  headers?: string[];
  rows?: (string | number)[][];
  // chart block
  chart_type?: 'bar' | 'line' | 'pie';
  title?: string;
  x_key?: string;
  data?: Record<string, any>[];
  series?: { key: string; label: string; color: string }[];
}

/** A single message in the chat UI (user or assistant). */
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  /** For user messages: single text block. For assistant: structured blocks. */
  blocks: ChatBlock[];
  timestamp: number;
}

/** Request body sent to POST /chatbot/chat */
export interface ChatRequest {
  message: string;
  session_id: string;
  /** Last N messages sent as plain text role+content pairs for Claude context */
  history: { role: string; content: string }[];
}

/** Response from POST /chatbot/chat */
export interface ChatResponse {
  blocks: ChatBlock[];
  session_id: string;
  raw_text?: string;
}
