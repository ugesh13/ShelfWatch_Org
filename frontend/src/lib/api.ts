import {
  AnalyticsSummary,
  AnomalyResult,
  APIResponse,
  DiffusionResult,
  DominoImpactResult,
  DominoScore,
  FacilityDetailData,
  Fingerprint,
  FixtureMeta,
  Plan,
  PlanComparisonData,
  Scenario,
  Assumptions,
  SnapshotSummary,
  SimulationRunData,
} from './types';

const BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Unexpected request failure';
}

function formatDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      if (item && typeof item === 'object' && 'msg' in item) {
        return String(item.msg);
      }
      return String(item);
    }).join('; ');
  }
  return 'The server rejected this request';
}

async function request<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  options?.signal?.addEventListener('abort', cancel, { once: true });
  if (options?.signal?.aborted) cancel();
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, 120_000);

  try {
    let response: Response;
    try {
      response = await fetch(BASE_URL + endpoint, {
        ...options,
        signal: controller.signal,
        headers: { 'Content-Type': 'application/json', ...options?.headers },
      });
    } catch (error) {
      if (options?.signal?.aborted) throw error;
      if (timedOut) throw new Error('Analysis timed out. Retry the request.');
      throw new Error('Cannot reach the backend. Check that the API server is running.');
    }
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const payload: { detail?: unknown } = await response.json();
        detail = formatDetail(payload.detail);
      } catch {
        // Preserve the HTTP status if a proxy returned an HTML error page.
      }
      throw new Error('API Error ' + response.status + ': ' + detail);
    }
    const json: APIResponse<T> = await response.json();
    if (!json || !('data' in json)) throw new Error('The backend returned an invalid response.');
    return json.data;
  } finally {
    clearTimeout(timeout);
    options?.signal?.removeEventListener('abort', cancel);
  }
}

export const api = {
  getHealth: () => request<{ status: string; schema_version: string; algorithm_version: string }>('/health'),

  getFixtures: (signal?: AbortSignal) => request<FixtureMeta[]>('/demo/fixtures', { signal }),

  createScenario: (fixtureId: string = 'shared_depot_delay', seed: number = 42, signal?: AbortSignal) =>
    request<Scenario>('/scenarios', {
      signal,
      method: 'POST',
      body: JSON.stringify({ fixture_id: fixtureId, seed, horizon_days: 14 }),
    }),

  getScenario: (scenarioId: string, revision?: number, signal?: AbortSignal) =>
    request<{ scenario: Scenario; snapshot: SnapshotSummary }>(
      `/scenarios/${scenarioId}${revision ? `?revision=${revision}` : ''}`, { signal }
    ),

  patchScenario: (
    scenarioId: string,
    patch: {
      expected_revision: number;
      demand_overrides: Assumptions['demand_overrides'];
      depot_delays: Assumptions['depot_delays'];
      closed_route_ids: string[];
      seed?: number;
    },
    signal?: AbortSignal
  ) =>
    request<Scenario>(`/scenarios/${scenarioId}`, {
      signal,
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  runSimulation: (scenarioId: string, skuId: string, revision: number, signal?: AbortSignal) =>
    request<SimulationRunData>(`/scenarios/${scenarioId}/run`, {
      signal,
      method: 'POST',
      body: JSON.stringify({ sku_id: skuId, expected_revision: revision }),
    }),

  getFacilityDetail: (scenarioId: string, facilityId: string, skuId: string, revision?: number, signal?: AbortSignal) =>
    request<FacilityDetailData>(
      `/scenarios/${scenarioId}/facilities/${facilityId}?sku_id=${skuId}${
        revision ? `&revision=${revision}` : ''
      }`, { signal }
    ),

  runImpact: (scenarioId: string, skuId: string, revision: number, signal?: AbortSignal) =>
    request<DominoImpactResult[]>(`/scenarios/${scenarioId}/impact`, {
      signal,
      method: 'POST',
      body: JSON.stringify({ sku_id: skuId, expected_revision: revision }),
    }),

  generatePlans: (scenarioId: string, skuId: string, revision: number, policy: string = 'shelfwatch', signal?: AbortSignal) =>
    request<PlanComparisonData>(`/scenarios/${scenarioId}/plans?policy=${policy}`, {
      signal,
      method: 'POST',
      body: JSON.stringify({ sku_id: skuId, expected_revision: revision }),
    }),

  getPlan: (planId: string) => request<Plan>(`/plans/${planId}`),

  reviewPlan: (planId: string, revision: number, action: 'APPROVE' | 'REJECT', reason?: string, signal?: AbortSignal) =>
    request<Plan>(`/plans/${planId}/review`, {
      signal,
      method: 'POST',
      body: JSON.stringify({ expected_revision: revision, action, reason }),
    }),

  // ═══════════════════════════════════════════════════════════════════
  // DIFFERENTIATOR ENDPOINTS — D1 Domino, D2 Fingerprint, D3 Diffusion
  // ═══════════════════════════════════════════════════════════════════

  /** ⭐ CUSUM + z-score anomaly detection for all facilities */
  getRiskScores: (scenarioId: string, skuId: string, revision: number, signal?: AbortSignal) =>
    request<AnomalyResult[]>(`/scenarios/${scenarioId}/risk-scores`, {
      signal,
      method: 'POST',
      body: JSON.stringify({ sku_id: skuId, expected_revision: revision }),
    }),

  /** ⭐ D2 Shortage Fingerprinting — classify shortage TYPE */
  getFingerprints: (scenarioId: string, skuId: string, revision: number, signal?: AbortSignal) =>
    request<Fingerprint[]>(`/scenarios/${scenarioId}/fingerprints`, {
      signal,
      method: 'POST',
      body: JSON.stringify({ sku_id: skuId, expected_revision: revision }),
    }),

  /** ⭐ D1 Domino Index — structural vulnerability scoring */
  getDominoIndex: (scenarioId: string, skuId: string, revision: number, signal?: AbortSignal) =>
    request<DominoScore[]>(`/scenarios/${scenarioId}/domino-index`, {
      signal,
      method: 'POST',
      body: JSON.stringify({ sku_id: skuId, expected_revision: revision }),
    }),

  /** ⭐ D3 SIS Contagion Diffusion — cascade simulation */
  getDiffusion: (scenarioId: string, skuId: string, revision: number, signal?: AbortSignal) =>
    request<DiffusionResult>(`/scenarios/${scenarioId}/diffusion`, {
      signal,
      method: 'POST',
      body: JSON.stringify({ sku_id: skuId, expected_revision: revision }),
    }),

  /** Combined analytics summary for dashboard KPIs */
  getAnalyticsSummary: (scenarioId: string, skuId: string, revision: number, signal?: AbortSignal) =>
    request<AnalyticsSummary>(`/scenarios/${scenarioId}/analytics`, {
      signal,
      method: 'POST',
      body: JSON.stringify({ sku_id: skuId, expected_revision: revision }),
    }),
};
