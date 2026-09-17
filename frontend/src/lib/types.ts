export interface APIResponse<T> {
  data: T;
  meta: {
    computed_at: string;
    schema_version: string;
  };
}

export interface Product {
  sku_id: string;
  generic_name: string;
  strength: string;
  dosage_form: string;
  base_unit: string;
  storage_class: 'ROOM_TEMPERATURE' | 'COLD_CHAIN';
}

export interface Facility {
  id: string;
  name: string;
  type: 'DH' | 'CHC' | 'PHC' | 'SC';
  lat: number;
  lon: number;
  depot_id: string;
  is_simulated: boolean;
}

export interface Depot {
  id: string;
  name: string;
  lat: number;
  lon: number;
}

export interface Route {
  id: string;
  from_id: string;
  to_id: string;
  kind: 'SUPPLY' | 'TRANSFER';
  distance_km: number;
  transit_days: number;
  enabled: boolean;
}

export interface DemandOverride {
  facility_id: string;
  sku_id: string;
  multiplier: number;
  start_day?: number;
  end_day?: number;
}

export interface DepotDelay {
  depot_id: string;
  extra_days: number;
}

export interface Assumptions {
  demand_overrides: DemandOverride[];
  depot_delays: DepotDelay[];
  closed_route_ids: string[];
}

export interface Scenario {
  id: string;
  snapshot_id: string;
  fixture_id: string | null;
  name: string;
  as_of: string;
  seed: number;
  horizon_days: number;
  revision: number;
  assumptions: Assumptions;
}

export interface SnapshotSummary {
  id: string;
  name: string;
  as_of: string;
  facilities: Facility[];
  depots: Depot[];
  products: Product[];
  routes: Route[];
}

export interface FixtureMeta {
  id: string;
  name: string;
  description: string;
  mode: 'stochastic' | 'deterministic';
}

export interface FactorExplanation {
  code: string;
  category: 'inventory' | 'supply' | 'demand' | 'network' | 'data';
  title: string;
  description: string;
  priority: number;
}

export interface FacilityRiskSummary {
  facility_id: string;
  sku_id: string;
  risk_state: 'Empty' | 'High risk' | 'Watch' | 'Lower risk' | 'Unknown';
  shortage_probability_7d: number | null;
  shortage_probability_14d: number | null;
  expected_unmet_units_14d: number | null;
  first_shortfall_day_p10: number | null;
  first_shortfall_day_p50: number | null;
  first_shortfall_day_p90: number | null;
  current_usable_stock: number | null;
  daily_shortage_probability: (number | null)[];
  daily_stock_p50: (number | null)[];
  daily_risk_state: FacilityRiskSummary['risk_state'][];
  primary_factors: FactorExplanation[];
  all_factors: FactorExplanation[];
  flags: string[];
}

export interface SimulationRunData {
  scenario_id: string;
  revision: number;
  sku_id: string;
  horizon_days: number;
  metrics: {
    expected_unmet_units: number;
    expected_facility_days: number;
    expected_expiry_units: number;
  };
  facilities: FacilityRiskSummary[];
  path_count: number;
  assumptions: string[];
  excluded_facility_ids: string[];
}

export interface HistoryRow {
  date: string;
  requested_units: number | null;
  fulfilled_units: number;
  closing_units: number;
  received_units: number;
}

export interface PendingShipment {
  id: string;
  depot_id: string;
  quantity_units: number;
  promised_arrival_day: number;
  current_eta_day: number;
  status: string;
  route_id: string;
  route_blocked: boolean;
  projected_arrival_day: number | null;
  expires_on: string;
}

export interface FacilityDetailData {
  facility_id: string;
  sku_id: string;
  scenario_id: string;
  revision: number;
  path_count: number;
  assumptions: string[];
  explanation: FacilityRiskSummary;
  stock_trajectory: {
    days: number[];
    p10: (number | null)[];
    p50: (number | null)[];
    p90: (number | null)[];
  };
  history: HistoryRow[];
  pending_shipments: PendingShipment[];
}

export interface DominoImpactResult {
  depot_id: string;
  depot_name: string;
  additional_affected_facilities_mean: number;
  additional_affected_facilities_p10: number;
  additional_affected_facilities_p50: number;
  additional_affected_facilities_p90: number;
  additional_unmet_units_mean: number;
  additional_unmet_units_p10: number;
  additional_unmet_units_p50: number;
  additional_unmet_units_p90: number;
  newly_affected_facility_ids: string[];
  tested_extra_days: number;
  horizon_days: number;
  excluded_facility_ids: string[];
  modeled_facility_count: number;
}

export interface BatchAllocation {
  batch_id: string;
  quantity_units: number;
}

export interface Transfer {
  id: string;
  from_facility_id: string;
  to_facility_id: string;
  sku_id: string;
  quantity_units: number;
  route_id: string;
  dispatch_day: number;
  arrival_day: number;
  batch_allocations: BatchAllocation[];
}

export interface RecommendationItem {
  id: string;
  from_facility_id: string;
  to_facility_id: string;
  sku_id: string;
  quantity_units: number;
  route_id: string;
  dispatch_day: number;
  arrival_day: number;
  batch_allocations: BatchAllocation[];
  planning_unmet_units_avoided: number;
  donor_minimum_planning_stock: number;
  donor_reserve_at_minimum_day: number;
  sampled_donor_harm_paths: number;
  status: 'DRAFT' | 'APPROVED' | 'REJECTED';
}

export interface PlanMetrics {
  expected_unmet_units: number;
  expected_facility_days: number;
  expected_expiry_units: number;
  expected_additional_donor_unmet: number;
  transfer_units: number;
  transfer_distance: number;
  unmet_units_avoided: number;
}

export interface Plan {
  id: string;
  scenario_id: string;
  scenario_revision: number;
  sku_id: string;
  policy: 'no_action' | 'nearest_donor' | 'shelfwatch';
  status: 'DRAFT' | 'APPROVED' | 'REJECTED';
  transfers: Transfer[];
  recommendations: RecommendationItem[];
  metrics: PlanMetrics;
  residual_deficit: number;
  constraint_checks: Record<string, boolean>;
  notes: string[];
  excluded_facility_ids: string[];
  modeled_facility_count: number;
}

export interface PlanComparisonData {
  selected_plan: Plan;
  comparison: {
    no_action: {
      id: string;
      policy: string;
      metrics: PlanMetrics;
      transfer_count: number;
      residual_deficit: number;
    };
    nearest_donor: {
      id: string;
      policy: string;
      metrics: PlanMetrics;
      transfer_count: number;
      residual_deficit: number;
    };
    shelfwatch: {
      id: string;
      policy: string;
      metrics: PlanMetrics;
      transfer_count: number;
      residual_deficit: number;
    };
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// DIFFERENTIATOR TYPES — D1 Domino Index, D2 Fingerprinting, D3 Diffusion
// ═══════════════════════════════════════════════════════════════════════════════

export type ShortageType = 'DEMAND_SURGE' | 'SUPPLY_DISRUPTION' | 'PANIC_HOARDING' | 'CHRONIC_EROSION' | 'MIXED';
export type RiskLevel = 'STABLE' | 'AT_RISK' | 'CRITICAL' | 'STOCKOUT' | 'UNKNOWN';

/** CUSUM + z-score anomaly detection result per facility */
export interface AnomalyResult {
  facility_id: string;
  drug_id: string;
  local_risk_score: number | null;
  risk_level: RiskLevel;
  z_score: number | null;
  cusum_upper: number | null;
  cusum_lower: number | null;
  days_of_stock: number | null;
  flag_reasons: string[];
  detected_at: number;
}

/** ⭐ D2 Shortage Fingerprinting — classifies WHY a shortage is happening */
export interface Fingerprint {
  facility_id: string;
  drug_id: string;
  shortage_type: ShortageType;
  confidence: number;
  rule_score: number;
  confidence_kind: 'heuristic_not_probability';
  signature: {
    spike_ratio: number;
    supply_gap_days: number;
    max_single_day_ratio: number;
    trend_slope: number;
    neighbor_z_mean: number;
  };
  recommended_intervention: string;
}

/** ⭐ D1 Domino Index — structural vulnerability scoring */
export interface DominoScore {
  facility_id: string;
  domino_index: number | null;
  betweenness_centrality: number;
  isolation_score: number;
  dependency_fan_out: number;
  vulnerability_rank: number;
  risk_narrative: string;
}

/** ⭐ D3 SIS Contagion Diffusion — timeline point */
export interface TimelinePoint {
  day: number;
  facilities_stable: number;
  facilities_at_risk: number;
  facilities_critical: number;
  regional_risk_score: number | null;
  facilities_unknown: number;
}

/** Per-facility projection from diffusion model */
export interface FacilityProjection {
  day_entered_at_risk: number | null;
  day_entered_critical: number | null;
  risk_trajectory: (number | null)[];
}

/** ⭐ D3 Full diffusion result */
export interface DiffusionResult {
  simulation_days: number;
  timeline: TimelinePoint[];
  facility_projections: Record<string, FacilityProjection>;
  model_kind: 'heuristic_graph';
  assumptions: string[];
}

/** Combined analytics summary */
export interface AnalyticsSummary {
  total_facilities: number;
  facilities_at_risk: number;
  facilities_critical: number;
  regional_risk_score: number | null;
  facilities_unknown: number;
  score_kind: 'heuristic_not_probability';
  worst_facility: {
    id: string;
    risk_score: number;
    days_of_stock: number | null;
  } | null;
  top_domino_facility: {
    id: string;
    domino_index: number;
    vulnerability_rank: number;
  } | null;
  shortage_type_distribution: Partial<Record<ShortageType, number>>;
  diffusion_day_14: TimelinePoint | null;
  pending_recommendations: number;
}
