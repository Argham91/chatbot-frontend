
import axios from 'axios';
import { 
  ProductionKPIs,
  PlanningKPIs,
  GradeWiseRomData, 
  DayWiseGradeRomData, 
  DayWiseCr2O3Data, 
  DayWiseGradeCr2O3Data,
  LocationSummaryData,
  LocationDayWiseRawItem,
  PlannedVsActualData,
  MrlPlanningData,
  InsightsResponse,
  PlanningLocation,
  PlanningCapabilities,
  IntegratedPlanningItem,
  ChemistryItem,
  DayWeekCuttingPlanResponse,
  // Raw Types
  RomTotalResponse,
  WeightedAvgCr2O3Response,
  GradeWiseRomRawResponse,
  DayWiseGradeRawItem,
  DayWiseCr2O3RawItem,
  DayWiseGradeCr2O3RawItem,
  LocationSummaryRawItem,
  TotalOrePlanResponse,
  TotalObPlanResponse,
  TotalLocationOreObRawItem,
  PlannedVsActualRawResponse,
  MrlPlanRawItem,
  SiltTotalResponse,
  // Quality Types
  QualityAllResponse,
  QualityTimeSeriesItem,
  QualityRawItem,
  QualityFlowItem,
  QualityKpiResponse,
  QualityStageTotalItem,
  QualityDatewiseItem,
  QualityAreaItem,
  SynopsisResponse
} from '../types';
import { objectToChartArray, safeNumber } from '../utils/transform';

// Dynamic API base URL — forces IPv4 (127.0.0.1) when running on localhost
// to avoid IPv6 (::1) resolution delays that cause 30s timeouts.
// For all other hosts (e.g. 192.168.x.x), hostname passes through unchanged.
const _hostname = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
const _apiHostname = _hostname === 'localhost' ? '127.0.0.1' : _hostname;
const API_BASE = (import.meta as any).env?.VITE_API_BASE || `http://${_apiHostname}:8001`;

const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
});

export const formatDateParam = (date: Date): string => {
  // Use local date components instead of toISOString() to avoid UTC timezone shift.
  // In IST (UTC+5:30), toISOString() converts midnight local to the previous day in UTC
  // (e.g. Jan 31 00:00 IST → "2026-01-30T18:30:00Z"), causing all preset date ranges
  // to silently send the wrong start/end dates to the API.
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
};

const fetchData = async <T>(endpoint: string, startDate: Date, endDate: Date): Promise<T> => {
  try {
    const response = await api.get<T>(endpoint, {
      params: {
        start_date: formatDateParam(startDate),
        end_date: formatDateParam(endDate),
      },
    });
    return response.data;
  } catch (error) {
    console.warn(`Error fetching ${endpoint}:`, error);
    throw error;
  }
};

const fetchDataWithParams = async <T>(endpoint: string, startDate: Date, endDate: Date, locId?: number): Promise<T> => {
  try {
    const params: any = {
      start_date: formatDateParam(startDate),
      end_date: formatDateParam(endDate),
    };
    if (locId) params.loc_id = locId;

    const response = await api.get<T>(endpoint, { params });
    return response.data;
  } catch (error) {
    console.warn(`Error fetching ${endpoint}:`, error);
    throw error;
  }
};

// ==========================================
// PRODUCTION API
// ==========================================

export const fetchProductionKpis = async (start: Date, end: Date): Promise<ProductionKPIs> => {
  try {
    const [romRes, cr2o3Res, locRes, siltRes] = await Promise.all([
      fetchData<RomTotalResponse>('/production/rom_total', start, end).catch(() => ({ rom_total_Mt: 0 })),
      fetchData<WeightedAvgCr2O3Response>('/production/weighted_avg_cr2o3', start, end).catch(() => ({ weighted_avg_cr2o3: 0 })),
      fetchData<LocationSummaryRawItem[]>('/production/location_summary', start, end).catch(() => []),
      fetchData<SiltTotalResponse>('/production/silt_removal_total', start, end).catch(() => ({ silt_total_cum: 0 }))
    ]);

    const romTotal = safeNumber(romRes?.rom_total_Mt);
    const avgCr2o3 = safeNumber(cr2o3Res?.weighted_avg_cr2o3);
    
    const safeLocSummary = Array.isArray(locRes) ? locRes : [];
    const obTotal = safeLocSummary.reduce((acc, curr) => acc + safeNumber(curr.ob_cum), 0);
    const strippingRatio = romTotal > 0 ? obTotal / romTotal : 0;

    const siltRemoval = safeNumber(siltRes?.silt_total_cum);

    return { romTotal, avgCr2o3, obTotal, strippingRatio, siltRemoval };
  } catch (e) {
    return { romTotal: 0, avgCr2o3: 0, obTotal: 0, strippingRatio: 0, siltRemoval: 0 };
  }
};

export const fetchGradeWiseRom = async (start: Date, end: Date): Promise<GradeWiseRomData[]> => {
  try {
    const raw = await fetchData<GradeWiseRomRawResponse>('/production/grade_wise_rom', start, end);
    return objectToChartArray(raw, 'grade', 'tonnage') as GradeWiseRomData[];
  } catch (e) {
    return [];
  }
};

export const fetchDayWiseGradeRom = async (start: Date, end: Date): Promise<DayWiseGradeRomData[]> => {
  try {
    const raw = await fetchData<DayWiseGradeRawItem[]>('/production/daywise_gradewise_rom', start, end);
    if (!Array.isArray(raw)) return [];
    
    const grouped: Record<string, DayWiseGradeRomData> = {};

    raw.forEach(item => {
      const date = item.Prod_date;
      if (!grouped[date]) {
        grouped[date] = { date, hg: 0, mg: 0, lg: 0, total: 0 };
      }
      const qty = safeNumber(item.qty_Mt);
      if (item.grade === 'High') grouped[date].hg += qty;
      else if (item.grade === 'Medium') grouped[date].mg += qty;
      else if (item.grade === 'Low') grouped[date].lg += qty;
      grouped[date].total += qty;
    });

    return Object.values(grouped).sort((a, b) => a.date.localeCompare(b.date));
  } catch (e) {
    return [];
  }
};

export const fetchDayWiseCr2o3 = async (start: Date, end: Date): Promise<DayWiseCr2O3Data[]> => {
  try {
    const raw = await fetchData<DayWiseCr2O3RawItem[]>('/production/daywise_weighted_cr2o3', start, end);
    if (!Array.isArray(raw)) return [];
    return raw.map(item => ({
      date: item.Prod_date,
      cr2o3: safeNumber(item.weighted_cr2o3_pct)
    }));
  } catch (e) {
    return [];
  }
};

export const fetchDayWiseGradeCr2O3 = async (start: Date, end: Date): Promise<DayWiseGradeCr2O3Data[]> => {
  try {
    const raw = await fetchData<DayWiseGradeCr2O3RawItem[]>('/production/daywise_grade_cr2o3', start, end);
    if (!Array.isArray(raw)) return [];
    const map: Record<string, any> = {};
    raw.forEach(r => {
      if (!map[r.Prod_date]) {
        map[r.Prod_date] = { date: r.Prod_date, high: 0, medium: 0, low: 0 };
      }
      const key = r.grade.toLowerCase(); 
      if (key.includes('high')) map[r.Prod_date].high = safeNumber(r.weighted_cr2o3_pct);
      else if (key.includes('medium')) map[r.Prod_date].medium = safeNumber(r.weighted_cr2o3_pct);
      else if (key.includes('low')) map[r.Prod_date].low = safeNumber(r.weighted_cr2o3_pct);
    });
    return Object.values(map).sort((a: any, b: any) => a.date.localeCompare(b.date));
  } catch (e) {
    return [];
  }
};

export const fetchLocationSummary = async (start: Date, end: Date): Promise<LocationSummaryData[]> => {
  try {
    const raw = await fetchData<LocationSummaryRawItem[]>('/production/location_summary', start, end);
    if (!Array.isArray(raw)) return [];
    return raw.map(item => {
      const rom = safeNumber(item.rom_Mt);
      const ob = safeNumber(item.ob_cum);
      return {
        id: item.Loc_Id,
        location_name: item.Loc_Desc || `Loc ${item.Loc_Id}`,
        rom_tonnage: rom,
        ob_volume: ob,
        stripping_ratio: rom > 0 ? ob / rom : 0
      };
    });
  } catch (e) {
    return [];
  }
};

export const fetchLocationDayWiseRaw = async (start: Date, end: Date): Promise<LocationDayWiseRawItem[]> => {
  try {
    const raw = await fetchData<LocationDayWiseRawItem[]>('/production/location_daywise_rom_ob', start, end);
    return Array.isArray(raw) ? raw : [];
  } catch (e) {
    return [];
  }
};

// ==========================================
// PLANNING API
// ==========================================

export const fetchPlanningLocations = async (): Promise<PlanningLocation[]> => {
  try {
    const response = await api.get<PlanningLocation[]>('/planning/locations');
    return response.data || [];
  } catch (e) {
    return [];
  }
};

export const fetchPlanningCapabilities = async (): Promise<PlanningCapabilities> => {
  try {
    const response = await api.get<PlanningCapabilities>('/planning/capabilities');
    return response.data;
  } catch (e) {
    return {
      has_monthly_table: true,
      has_daily_table: true,
      has_location_master: true,
      monthly_has_cr2o3: false,
      monthly_has_crfe: false,
      daily_has_cr2o3: false,
      daily_has_grades: false,
      notes: [],
    };
  }
};

export const fetchPlanningKpis = async (start: Date, end: Date, locId?: number): Promise<PlanningKPIs> => {
  try {
    const [orePlan, obPlanRes] = await Promise.all([
      fetchDataWithParams<TotalOrePlanResponse>('/planning/total_ore_production_plan', start, end, locId).catch(() => null),
      fetchDataWithParams<TotalObPlanResponse>('/planning/total_ob_plan', start, end, locId).catch(() => null)
    ]);
    const totalPlannedOre = safeNumber(orePlan?.total_ore);
    const plannedHg = safeNumber(orePlan?.total_HG);
    const plannedMg = safeNumber(orePlan?.total_MG);
    const plannedLg = safeNumber(orePlan?.total_LG);
    const totalPlannedOb = safeNumber(obPlanRes?.total_ob_plan_cum);
    return { totalPlannedOre, plannedHg, plannedMg, plannedLg, totalPlannedOb };
  } catch (e) {
    return { totalPlannedOre: 0, plannedHg: 0, plannedMg: 0, plannedLg: 0, totalPlannedOb: 0 };
  }
};

export const fetchPlannedVsActualOre = async (start: Date, end: Date, locId?: number): Promise<PlannedVsActualData[]> => {
  try {
    const raw = await fetchDataWithParams<PlannedVsActualRawResponse>('/planning/planned_vs_actual?type=ore', start, end, locId);
    const list = raw?.daywise;
    if (!Array.isArray(list)) return [];
    return list.map(item => ({
      date: item.Prod_date,
      planned: safeNumber(item.planned_ore),
      actual: safeNumber(item.actual_ore)
    }));
  } catch (e) {
    return [];
  }
};

export const fetchPlannedVsActualOb = async (start: Date, end: Date, locId?: number): Promise<PlannedVsActualData[]> => {
  try {
    const raw = await fetchDataWithParams<PlannedVsActualRawResponse>('/planning/planned_vs_actual?type=ob', start, end, locId);
    const list = raw?.daywise;
    if (!Array.isArray(list)) return [];
    return list.map(item => ({
      date: item.Prod_date,
      planned: safeNumber(item.planned_ob),
      actual: safeNumber(item.actual_ob)
    }));
  } catch (e) {
    return [];
  }
};

export const fetchMrlProductionPlan = async (start: Date, end: Date, locId?: number): Promise<MrlPlanningData[]> => {
  try {
    const raw = await fetchDataWithParams<MrlPlanRawItem[]>('/planning/location_mrl_production_plan', start, end, locId);
    if (!Array.isArray(raw)) return [];
    return raw.map(item => ({
      mrl: item.Z_Range || 'Unknown',
      planned_ore: safeNumber(item.planned_ore),
      planned_ob: safeNumber(item.planned_ob)
    }));
  } catch (e) {
    return [];
  }
};

export const fetchIntegratedPlanningTable = async (start: Date, end: Date, locId?: number): Promise<IntegratedPlanningItem[]> => {
  try {
    return await fetchDataWithParams<IntegratedPlanningItem[]>('/planning/integrated_planning_table', start, end, locId);
  } catch (e) {
    return [];
  }
};

export const fetchIntegratedPlanningExportUrl = async (start: Date, end: Date, locId?: number): Promise<string> => {
  try {
    const params: any = { 
      start_date: formatDateParam(start), 
      end_date: formatDateParam(end),
      export: 'true'
    };
    if (locId) params.loc_id = locId;
    const response = await api.get('/planning/integrated_planning_table', { params });
    return response.data; 
  } catch (e) {
    throw e;
  }
};

export const fetchLocationMrlCr2o3CrFe = async (start: Date, end: Date, locId?: number): Promise<ChemistryItem[]> => {
  try {
    return await fetchDataWithParams<ChemistryItem[]>('/planning/location_mrl_cr2o3_crfe', start, end, locId);
  } catch (e) {
    return [];
  }
};

export const fetchDayWeekMrlCuttingPlan = async (start: Date, end: Date, locId?: number): Promise<DayWeekCuttingPlanResponse> => {
  try {
    return await fetchDataWithParams<DayWeekCuttingPlanResponse>('/planning/day_week_mrl_cutting_plan', start, end, locId);
  } catch (e) {
    return { daywise: [], weekwise: [], mrl_monthly: [] };
  }
};

// ==========================================
// QUALITY API (Refactored)
// ==========================================

// Legacy endpoint support (optional, if old code uses it)
export const fetchQualityAll = async (start: Date, end: Date): Promise<QualityAllResponse> => {
  return fetchData<QualityAllResponse>('/quality/all', start, end);
};

export const fetchQualityKpis = async (start: Date, end: Date): Promise<QualityKpiResponse> => {
  return fetchData<QualityKpiResponse>('/quality/kpis', start, end);
};

export const fetchQualityStageTotals = async (start: Date, end: Date): Promise<QualityStageTotalItem[]> => {
  try {
    const res = await fetchData<QualityStageTotalItem[]>('/quality/stage-totals', start, end);
    return Array.isArray(res) ? res : [];
  } catch (e) {
    return [];
  }
};

export const fetchQualityDatewise = async (start: Date, end: Date): Promise<QualityDatewiseItem[]> => {
  try {
    const res = await fetchData<QualityDatewiseItem[]>('/quality/datewise', start, end);
    return Array.isArray(res) ? res : [];
  } catch (e) {
    return [];
  }
};

export const fetchQualityStacked = async (start: Date, end: Date): Promise<QualityDatewiseItem[]> => {
  // Re-uses datewise endpoint logic on frontend or separate endpoint if backend requires
  try {
    const res = await fetchData<QualityDatewiseItem[]>('/quality/stacked', start, end);
    return Array.isArray(res) ? res : [];
  } catch (e) {
    return [];
  }
};

export const fetchQualityAreaWise = async (start: Date, end: Date): Promise<QualityAreaItem[]> => {
  try {
    const res = await fetchData<QualityAreaItem[]>('/quality/area-wise', start, end);
    return Array.isArray(res) ? res : [];
  } catch (e) {
    return [];
  }
};

export const fetchQualityTimeSeries = async (start: Date, end: Date, area?: string): Promise<QualityTimeSeriesItem[]> => {
  try {
    const params: any = {
      start_date: formatDateParam(start),
      end_date: formatDateParam(end),
    };
    if (area && area !== 'All') params.area = area;
    const response = await api.get<QualityTimeSeriesItem[]>('/quality/timeseries', { params });
    return response.data;
  } catch (e) {
    return [];
  }
};

export const fetchQualityRaw = async (start: Date, end: Date, limit: number = 100): Promise<QualityRawItem[]> => {
  try {
    const params: any = {
      start_date: formatDateParam(start),
      end_date: formatDateParam(end),
      limit
    };
    const response = await api.get<QualityRawItem[]>('/quality/raw', { params });
    return response.data;
  } catch (e) {
    return [];
  }
};

// ==========================================
// INSIGHTS API
// ==========================================

export const fetchCombinedInsights = (start: Date, end: Date) => 
  fetchData<any>('/kpis/production_and_planning', start, end).catch(() => ({}));

export const fetchProductionInsights = async (start: Date, end: Date): Promise<InsightsResponse> => {
  return fetchData<InsightsResponse>('/insights/production', start, end);
};

export const fetchPlanningInsights = async (start: Date, end: Date): Promise<InsightsResponse> => {
  return fetchData<InsightsResponse>('/insights/planning', start, end);
};

// ==========================================
// CHATBOT API
// ==========================================

import { ChatRequest, ChatResponse } from '../types';

/**
 * Send a chat message to the IMOS AI Chatbot backend.
 * Uses a 120s timeout — analytical queries call 3 DB tools + 2 OpenAI rounds
 * and can legitimately take 60-90s under normal load.
 */
export const sendChatMessage = async (req: ChatRequest): Promise<ChatResponse> => {
  const response = await api.post<ChatResponse>('/chatbot/chat', req, { timeout: 120000 });
  return response.data;
};

/** Force an immediate schema re-discovery on the backend. */
export const refreshChatbotSchema = async (): Promise<void> => {
  await api.post('/chatbot/refresh-schema');
};

// ── Synopsis ──────────────────────────────────────────────────────────────────

export const fetchSynopsisMinesPerformance = async (start: Date, end: Date): Promise<SynopsisResponse> => {
  const response = await api.get<SynopsisResponse>('/synopsis/mines-performance', {
    params: {
      start_date: formatDateParam(start),
      end_date:   formatDateParam(end),
    },
  });
  return response.data;
};

export const fetchSynopsisWeather = async (): Promise<any> => {
  const response = await api.get('/synopsis/weather');
  return response.data;
};
