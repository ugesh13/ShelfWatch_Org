import { useState, useEffect, useCallback, useRef } from 'react';
import { motion } from 'framer-motion';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Shield,
  TrendingDown,
  Truck,
  Info,
  Sparkles,
  ServerCrash,
  RefreshCw,
} from 'lucide-react';
import { api, errorMessage } from './lib/api';
import {
  AnomalyResult,
  Assumptions,
  Depot,
  DiffusionResult,
  DominoImpactResult,
  DominoScore,
  Facility,
  FacilityDetailData,
  FacilityRiskSummary,
  Fingerprint,
  FixtureMeta,
  PlanComparisonData,
  Product,
  Route,
  Scenario,
  SimulationRunData,
} from './lib/types';
import { Header } from './components/Header';
import { FacilityMap } from './components/FacilityMap';
import { FacilityDrawer } from './components/FacilityDrawer';
import { ScenarioControls } from './components/ScenarioControls';
import { DominoImpact } from './components/DominoImpact';
import { PlanComparison } from './components/PlanComparison';
import { ContagionPanel } from './components/ContagionPanel';

export default function App() {
  const [fixtures, setFixtures] = useState<FixtureMeta[]>([]);
  const [selectedFixtureId, setSelectedFixtureId] = useState('verified_delay');
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [depots, setDepots] = useState<Depot[]>([]);
  const [routes, setRoutes] = useState<Route[]>([]);
  const [selectedSkuId, setSelectedSkuId] = useState('AMX500_CAP');
  const [simulationData, setSimulationData] = useState<SimulationRunData | null>(null);
  const [facilityRisks, setFacilityRisks] = useState<Record<string, FacilityRiskSummary>>({});
  const [impactResults, setImpactResults] = useState<DominoImpactResult[]>([]);
  const [planData, setPlanData] = useState<PlanComparisonData | null>(null);
  const [anomalyResults, setAnomalyResults] = useState<AnomalyResult[]>([]);
  const [fingerprints, setFingerprints] = useState<Fingerprint[]>([]);
  const [dominoScores, setDominoScores] = useState<DominoScore[]>([]);
  const [diffusionResult, setDiffusionResult] = useState<DiffusionResult | null>(null);
  const [selectedFacilityId, setSelectedFacilityId] = useState<string | null>(null);
  const [facilityDetail, setFacilityDetail] = useState<FacilityDetailData | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailAttempt, setDetailAttempt] = useState(0);
  const [currentDay, setCurrentDay] = useState(0);
  const [showTransfers, setShowTransfers] = useState(true);
  const [isInitializing, setIsInitializing] = useState(true);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [isPatching, setIsPatching] = useState(false);
  const [isReviewing, setIsReviewing] = useState(false);
  const [analysisFailures, setAnalysisFailures] = useState<string[]>([]);
  const [bannerNotice, setBannerNotice] = useState<{ type: 'success' | 'info' | 'error'; message: string } | null>(null);

  const initializationRequest = useRef<AbortController | null>(null);
  const analysisRequest = useRef<AbortController | null>(null);
  const selectedSkuRef = useRef('AMX500_CAP');
  const currentContext = useRef<string | null>(null);
  const mutationVersion = useRef(0);

  const clearAnalysis = useCallback(() => {
    setSimulationData(null);
    setFacilityRisks({});
    setImpactResults([]);
    setPlanData(null);
    setAnomalyResults([]);
    setFingerprints([]);
    setDominoScores([]);
    setDiffusionResult(null);
    setAnalysisFailures([]);
  }, []);

  const runFullAnalysis = useCallback(async (scenarioId: string, skuId: string, revision: number) => {
    analysisRequest.current?.abort();
    const controller = new AbortController();
    analysisRequest.current = controller;
    setIsRunning(true);
    clearAnalysis();
    const { signal } = controller;
    try {
      const results = await Promise.allSettled([
        api.runSimulation(scenarioId, skuId, revision, signal),
        api.runImpact(scenarioId, skuId, revision, signal),
        api.generatePlans(scenarioId, skuId, revision, 'shelfwatch', signal),
        api.getRiskScores(scenarioId, skuId, revision, signal),
        api.getFingerprints(scenarioId, skuId, revision, signal),
        api.getDominoIndex(scenarioId, skuId, revision, signal),
        api.getDiffusion(scenarioId, skuId, revision, signal),
      ]);
      if (signal.aborted || analysisRequest.current !== controller) return;
      const [simulation, impact, plan, anomalies, patterns, domino, diffusion] = results;
      if (simulation.status === 'fulfilled') {
        setSimulationData(simulation.value);
        setFacilityRisks(Object.fromEntries(simulation.value.facilities.map((item) => [item.facility_id, item])));
      }
      if (impact.status === 'fulfilled') setImpactResults(impact.value);
      if (plan.status === 'fulfilled') setPlanData(plan.value);
      if (anomalies.status === 'fulfilled') setAnomalyResults(anomalies.value);
      if (patterns.status === 'fulfilled') setFingerprints(patterns.value);
      if (domino.status === 'fulfilled') setDominoScores(domino.value);
      if (diffusion.status === 'fulfilled') setDiffusionResult(diffusion.value);
      const labels = ['inventory forecast', 'depot impact', 'transfer plan', 'anomalies', 'fingerprints', 'domino index', 'diffusion'];
      const failures = results.flatMap((item, index) => item.status === 'rejected' ? [labels[index]] : []);
      setAnalysisFailures(failures);
      if (failures.length) {
        const failure = results.find((item) => item.status === 'rejected');
        setBannerNotice({
          type: 'error',
          message: 'Unavailable: ' + failures.join(', ') + '. ' +
            (failure?.status === 'rejected' ? errorMessage(failure.reason) : 'Retry the analysis.'),
        });
      }
    } finally {
      if (analysisRequest.current === controller) setIsRunning(false);
    }
  }, [clearAnalysis]);

  const initializeScenario = useCallback(async (fixtureId: string) => {
    initializationRequest.current?.abort();
    analysisRequest.current?.abort();
    const controller = new AbortController();
    initializationRequest.current = controller;
    mutationVersion.current += 1;
    currentContext.current = null;
    setIsInitializing(true);
    setIsRunning(false);
    setIsPatching(false);
    setIsReviewing(false);
    setBackendError(null);
    setBannerNotice(null);
    setScenario(null);
    setSelectedFacilityId(null);
    setFacilityDetail(null);
    setCurrentDay(0);
    clearAnalysis();
    try {
      const fixtureList = await api.getFixtures(controller.signal);
      if (controller.signal.aborted) return;
      setFixtures(fixtureList);
      const fixture = fixtureList.find((item) => item.id === fixtureId) || fixtureList[0];
      if (!fixture) throw new Error('No demo scenarios are available.');
      setSelectedFixtureId(fixture.id);
      const created = await api.createScenario(fixture.id, 42, controller.signal);
      if (controller.signal.aborted) return;
      const full = await api.getScenario(created.id, created.revision, controller.signal);
      if (controller.signal.aborted) return;
      const snapshot = full.snapshot;
      const product = snapshot.products.find((item) => item.sku_id === selectedSkuRef.current) || snapshot.products[0];
      if (!product) throw new Error('This scenario has no medicine catalogue.');
      selectedSkuRef.current = product.sku_id;
      setSelectedSkuId(product.sku_id);
      setProducts(snapshot.products);
      setFacilities(snapshot.facilities);
      setDepots(snapshot.depots);
      setRoutes(snapshot.routes);
      setScenario(created);
      currentContext.current = created.id + '/' + created.revision + '/' + product.sku_id;
      await runFullAnalysis(created.id, product.sku_id, created.revision);
    } catch (error) {
      if (!controller.signal.aborted) setBackendError(errorMessage(error));
    } finally {
      if (initializationRequest.current === controller) setIsInitializing(false);
    }
  }, [clearAnalysis, runFullAnalysis]);

  useEffect(() => {
    void initializeScenario('verified_delay');
    return () => {
      initializationRequest.current?.abort();
      analysisRequest.current?.abort();
      mutationVersion.current += 1;
    };
  }, [initializeScenario]);

  useEffect(() => {
    const controller = new AbortController();
    setFacilityDetail(null);
    setDetailError(null);
    if (!selectedFacilityId || !scenario) {
      setIsLoadingDetail(false);
      return () => controller.abort();
    }
    setIsLoadingDetail(true);
    void api.getFacilityDetail(scenario.id, selectedFacilityId, selectedSkuId, scenario.revision, controller.signal)
      .then((detail) => {
        if (!controller.signal.aborted) setFacilityDetail(detail);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setDetailError(errorMessage(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoadingDetail(false);
      });
    return () => controller.abort();
  }, [selectedFacilityId, scenario, selectedSkuId, detailAttempt]);

  const handleSelectFixture = (fixtureId: string) => {
    setSelectedFixtureId(fixtureId);
    void initializeScenario(fixtureId);
  };

  const handleSelectSku = (skuId: string) => {
    if (!scenario || !products.some((product) => product.sku_id === skuId)) return;
    selectedSkuRef.current = skuId;
    setSelectedSkuId(skuId);
    setBannerNotice(null);
    setCurrentDay(0);
    currentContext.current = scenario.id + '/' + scenario.revision + '/' + skuId;
    void runFullAnalysis(scenario.id, skuId, scenario.revision);
  };

  const handleRunSimulation = () => {
    if (!scenario) return;
    setBannerNotice(null);
    void runFullAnalysis(scenario.id, selectedSkuId, scenario.revision);
  };

  const handleApplyAssumptionsPatch = async (assumptions: Assumptions) => {
    if (!scenario) return;
    const context = currentContext.current;
    const version = ++mutationVersion.current;
    setIsPatching(true);
    setBannerNotice(null);
    analysisRequest.current?.abort();
    clearAnalysis();
    try {
      const updated = await api.patchScenario(scenario.id, {
        expected_revision: scenario.revision, ...assumptions,
      });
      if (context !== currentContext.current || version !== mutationVersion.current) return;
      setScenario(updated);
      currentContext.current = updated.id + '/' + updated.revision + '/' + selectedSkuId;
      setBannerNotice({ type: 'info', message: 'Scenario updated to revision #' + updated.revision + '.' });
      await runFullAnalysis(updated.id, selectedSkuId, updated.revision);
    } catch (error) {
      if (context === currentContext.current && version === mutationVersion.current) {
        setBannerNotice({ type: 'error', message: 'Scenario update failed: ' + errorMessage(error) });
      }
    } finally {
      if (version === mutationVersion.current) setIsPatching(false);
    }
  };

  const handleReviewPlan = async (planId: string, action: 'APPROVE' | 'REJECT') => {
    if (!scenario || !planData || planData.selected_plan.id !== planId) return;
    const context = currentContext.current;
    const version = ++mutationVersion.current;
    setIsReviewing(true);
    try {
      const reviewed = await api.reviewPlan(planId, scenario.revision, action);
      if (context !== currentContext.current || version !== mutationVersion.current) return;
      setPlanData((current) => current?.selected_plan.id === reviewed.id
        ? { ...current, selected_plan: reviewed } : current);
      setBannerNotice({
        type: 'success',
        message: 'Plan ' + (action === 'APPROVE' ? 'approval' : 'rejection') +
          ' recorded for scenario revision #' + scenario.revision + '.',
      });
    } catch (error) {
      if (context === currentContext.current && version === mutationVersion.current) {
        setBannerNotice({ type: 'error', message: 'Review failed: ' + errorMessage(error) });
      }
    } finally {
      if (version === mutationVersion.current) setIsReviewing(false);
    }
  };

  // ── Derived KPI Metrics ─────────────────────────────────────────────────────
  const hasForecast = Boolean(simulationData && simulationData.facilities.length > simulationData.excluded_facility_ids.length);
  const totalUnmetUnits = hasForecast ? simulationData!.metrics.expected_unmet_units : null;
  const highRiskCount = Object.values(facilityRisks).filter(
    (r) => r.risk_state === 'High risk' || r.risk_state === 'Empty'
  ).length;
  const watchCount = Object.values(facilityRisks).filter((r) => r.risk_state === 'Watch').length;
  const unmetAvoided = planData && planData.selected_plan.modeled_facility_count > 0 ? planData.selected_plan.metrics.unmet_units_avoided : null;
  const modeledCount = simulationData ? simulationData.facilities.length - simulationData.excluded_facility_ids.length : 0;
  const avoidedPercent = totalUnmetUnits !== null && unmetAvoided !== null && totalUnmetUnits > 0
    ? ((unmetAvoided / totalUnmetUnits) * 100).toFixed(0) + '%' : null;
  const activeTransfers = planData?.selected_plan.transfers || [];
  const selectedFacilityObj = facilities.find((f) => f.id === selectedFacilityId) || null;

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col selection:bg-primary/30">
      {/* Top Application Header */}
      <Header
        fixtures={fixtures}
        selectedFixtureId={selectedFixtureId}
        onSelectFixture={handleSelectFixture}
        products={products}
        selectedSkuId={selectedSkuId}
        onSelectSku={handleSelectSku}
        isRunning={isRunning || isInitializing || isPatching || isReviewing}
        selectorsDisabled={isInitializing || isPatching || isReviewing || !scenario}
        isConnected={Boolean(scenario) && !backendError}
        onRunSimulation={handleRunSimulation}
        revision={scenario?.revision || 1}
      />

      {/* Interactive Alert / Notification Banner */}
      {bannerNotice && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          role={bannerNotice.type === 'error' ? 'alert' : 'status'}
          className={`px-6 py-3 text-xs flex items-center justify-between border-b backdrop-blur-md transition-all ${
            bannerNotice.type === 'success'
              ? 'bg-emerald-950/60 border-emerald-500/40 text-emerald-300'
              : bannerNotice.type === 'error'
              ? 'bg-rose-950/60 border-rose-500/40 text-rose-300'
              : 'bg-blue-950/60 border-blue-500/40 text-blue-300'
          }`}
        >
          <div className="flex items-center gap-2.5 font-medium">
            {bannerNotice.type === 'success' ? (
              <CheckCircle2 className="size-4 text-emerald-400 shrink-0" />
            ) : bannerNotice.type === 'error' ? (
              <AlertTriangle className="size-4 text-rose-400 shrink-0" />
            ) : (
              <Info className="size-4 text-blue-400 shrink-0" />
            )}
            <span>{bannerNotice.message}</span>
          </div>
          <button
            aria-label="Dismiss notification"
            onClick={() => setBannerNotice(null)}
            className="text-muted-foreground hover:text-foreground font-bold px-2 py-0.5 rounded cursor-pointer"
          >
            &times;
          </button>
        </motion.div>
      )}

      {/* Main Workspace Layout */}
      <main className="flex-1 p-6 space-y-6 max-w-[1720px] mx-auto w-full">
        {isInitializing && !scenario ? (
          <p role="status" className="py-24 text-center text-muted-foreground">Loading scenario…</p>
        ) : backendError ? (
          <div className="min-h-[520px] flex flex-col items-center justify-center text-center p-8 bg-card/60 backdrop-blur-xl border border-white/[0.08] rounded-3xl shadow-2xl max-w-xl mx-auto my-12">
            <div className="size-16 rounded-2xl bg-rose-500/15 border border-rose-500/30 flex items-center justify-center text-rose-400 mb-5 shadow-inner">
              <ServerCrash className="size-8" />
            </div>
            <h2 className="text-xl font-extrabold text-white tracking-tight">ShelfWatch Engine Disconnected</h2>
            <p className="text-xs text-muted-foreground mt-2 max-w-md leading-relaxed">
              Could not load the scenario from{' '}
              <code className="text-rose-300 font-mono bg-rose-950/60 px-1.5 py-0.5 rounded border border-rose-500/30 font-semibold">
                {import.meta.env.VITE_API_BASE_URL || '/api'}
              </code>.
              {' '}{backendError}
            </p>
            <div className="mt-5 p-3.5 rounded-xl bg-slate-900 border border-border/80 text-left font-mono text-[11px] text-slate-300 w-full space-y-1">
              <div className="text-muted-foreground text-[10px] uppercase font-bold tracking-wider mb-1">
                Start the backend server in terminal:
              </div>
              <div className="text-emerald-400">cd backend</div>
              <div className="text-emerald-400">python -m uvicorn app.main:app --reload</div>
            </div>
            <button
              onClick={() => initializeScenario(selectedFixtureId)}
              disabled={isInitializing}
              className="mt-6 flex items-center gap-2 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-bold text-xs px-6 py-3 rounded-xl transition-all shadow-lg shadow-blue-500/25 disabled:opacity-50 cursor-pointer border border-blue-400/30"
            >
              <RefreshCw className={`size-4 ${isInitializing ? 'animate-spin' : ''}`} />
              <span>{isInitializing ? 'Reconnecting to API...' : 'Retry Connection'}</span>
            </button>
          </div>
        ) : (
          <>
            {simulationData && (
              <details className="rounded-xl border border-border p-3 text-xs text-muted-foreground">
                <summary className="cursor-pointer font-semibold">Model assumptions · {simulationData.path_count} sampled paths{simulationData.excluded_facility_ids.length ? ' · incomplete coverage' : ''}</summary>
                {simulationData.excluded_facility_ids.length > 0 && <p className="mt-2 text-amber-300">Regional metrics exclude facilities with missing or stale evidence: {simulationData.excluded_facility_ids.join(', ')}.</p>}
                <ul className="mt-2 space-y-1 list-disc pl-5">{simulationData.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul>
              </details>
            )}
            {/* KPI Summary Ribbons */}
            <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {/* Unmet Demand Card */}
              <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.05 }}
            whileHover={{ y: -2 }}
            className="bg-card/75 backdrop-blur-xl border border-white/[0.08] rounded-2xl p-5 shadow-lg flex items-center justify-between transition-all"
          >
            <div>
              <p className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider">
                14-Day Regional Deficit
              </p>
              <div className="flex items-baseline gap-2 mt-1.5">
                <span className="text-3xl font-black text-white tracking-tight">
                  {totalUnmetUnits === null ? '—' : Math.round(totalUnmetUnits)}
                </span>
                <span className="text-xs text-muted-foreground font-semibold">units</span>
              </div>
              <p className="text-[11px] text-rose-400 flex items-center gap-1.5 mt-1 font-medium">
                <TrendingDown className="size-3.5" />
                <span>Baseline unmitigated shortfall</span>
              </p>
            </div>
            <div className="size-11 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-center justify-center text-rose-400 shadow-inner">
              <AlertTriangle className="size-5" />
            </div>
          </motion.div>

          {/* High Risk Facilities Card */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            whileHover={{ y: -2 }}
            className="bg-card/75 backdrop-blur-xl border border-white/[0.08] rounded-2xl p-5 shadow-lg flex items-center justify-between transition-all"
          >
            <div>
              <p className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider">
                Vulnerable Facilities
              </p>
              <div className="flex items-baseline gap-2 mt-1.5">
                <span className="text-3xl font-black text-white tracking-tight">{hasForecast ? highRiskCount : '—'}</span>
                <span className="text-xs text-muted-foreground font-semibold">
                  critical &bull; {hasForecast ? watchCount : '—'} watch
                </span>
              </div>
              <p className="text-[11px] text-amber-400 flex items-center gap-1.5 mt-1 font-medium">
                <Activity className="size-3.5" />
                <span>{hasForecast ? ((highRiskCount / modeledCount) * 100).toFixed(0) + '% of ' + modeledCount + ' modeled facilities' : 'Forecast unavailable'}</span>
              </p>
            </div>
            <div className="size-11 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400 shadow-inner">
              <Activity className="size-5" />
            </div>
          </motion.div>

          {/* ShelfWatch Preventable Units Card */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 }}
            whileHover={{ y: -2 }}
            className="bg-card/75 backdrop-blur-xl border border-emerald-500/30 rounded-2xl p-5 shadow-[0_0_20px_-5px_rgba(16,185,129,0.2)] flex items-center justify-between transition-all"
          >
            <div>
              <p className="text-[11px] font-bold text-emerald-400 uppercase tracking-wider">
                Estimated Shortfall Reduction
              </p>
              <div className="flex items-baseline gap-2 mt-1.5">
                <span className="text-3xl font-black text-emerald-400 tracking-tight">
                  {unmetAvoided === null ? '—' : Math.round(unmetAvoided)}
                </span>
                <span className="text-xs text-emerald-300/80 font-semibold">
                  units{avoidedPercent !== null ? ' (' + avoidedPercent + ')' : ''}
                </span>
              </div>
              <p className="text-[11px] text-emerald-400 flex items-center gap-1.5 mt-1 font-medium">
                <CheckCircle2 className="size-3.5" />
                <span>{planData ? 'Based on sampled inventory paths' : 'Transfer plan unavailable'}</span>
              </p>
            </div>
            <div className="size-11 rounded-xl bg-emerald-500/15 border border-emerald-500/40 flex items-center justify-center text-emerald-400 shadow-inner">
              <Shield className="size-5" />
            </div>
          </motion.div>

          {/* Active Safe Transfers Card */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            whileHover={{ y: -2 }}
            className="bg-card/75 backdrop-blur-xl border border-white/[0.08] rounded-2xl p-5 shadow-lg flex items-center justify-between transition-all"
          >
            <div>
              <p className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider">
                Redistribution Plan
              </p>
              <div className="flex items-baseline gap-2 mt-1.5">
                <span className="text-3xl font-black text-white tracking-tight">
                  {planData ? activeTransfers.length : '—'}
                </span>
                <span className="text-xs text-muted-foreground font-semibold">transfers</span>
              </div>
              <p className="text-[11px] text-blue-400 flex items-center gap-1.5 mt-1 font-medium">
                <Truck className="size-3.5" />
                <span>Audit Status: <b>{planData?.selected_plan.status || 'Unavailable'}</b></span>
              </p>
            </div>
            <div className="size-11 rounded-xl bg-blue-500/10 border border-blue-500/30 flex items-center justify-center text-blue-400 shadow-inner">
              <Truck className="size-5" />
            </div>
          </motion.div>
        </section>

        {/* Interactive District War Room Map */}
        <section className="w-full">
          <FacilityMap
            facilities={facilities}
            depots={depots}
            routes={routes}
            facilityRisks={facilityRisks}
            closedRouteIds={scenario?.assumptions.closed_route_ids || []}
            selectedFacilityId={selectedFacilityId}
            onSelectFacility={(id) => setSelectedFacilityId(id)}
            activeTransfers={activeTransfers}
            showTransfers={showTransfers}
            onToggleTransfers={(show) => setShowTransfers(show)}
            currentDay={currentDay}
            onDayChange={(d) => setCurrentDay(d)}
          />
        </section>

        {/* Multi-Layer Analytics Grid: What-If Controls + Domino Impact (Left) & Plan Comparison (Right) */}
        <section className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column: What-If Assumptions & Domino Depot Vulnerability */}
          <div className="lg:col-span-5 space-y-6">
            <ScenarioControls
              currentAssumptions={
                scenario?.assumptions || {
                  demand_overrides: [],
                  depot_delays: [],
                  closed_route_ids: [],
                }
              }
              onApplyPatch={handleApplyAssumptionsPatch}
              isUpdating={isPatching || isInitializing || isReviewing || !scenario}
              targetFacilityId={
                selectedFixtureId.startsWith('verified_')
                  ? 'F-A'
                  : facilities.find((f) => f.id === 'F-01')?.id || facilities[0]?.id || 'F-01'
              }
              targetRouteId={
                selectedFixtureId.startsWith('verified_')
                  ? 'B_TO_A'
                  : routes.find((r) => r.id === 'T-F-10-F-01')?.id || routes.find((r) => r.kind === 'TRANSFER')?.id || 'T-F-10-F-01'
              }
              selectedSkuId={selectedSkuId}
            />

            <DominoImpact
              impactResults={impactResults}
              error={analysisFailures.includes('depot impact') ? 'Depot impact unavailable. Run the analysis again.' : null}
              isLoading={isRunning || isInitializing}
            />
          </div>

          {/* Right Column: Multi-Policy Comparison & Safe Transfer Approval */}
          <div className="lg:col-span-7">
            <PlanComparison
              planData={planData}
              isLoading={isRunning || isInitializing}
              onApprovePlan={(id) => void handleReviewPlan(id, 'APPROVE')}
              onRejectPlan={(id) => void handleReviewPlan(id, 'REJECT')}
              isReviewing={isReviewing || isPatching}
              error={analysisFailures.includes('transfer plan') ? 'Transfer plan unavailable. Run the analysis again.' : null}
            />
          </div>
        </section>

        {/* ⭐ Contagion Intelligence Panel — D1/D2/D3 Differentiators */}
        <section className="w-full">
          <ContagionPanel
            error={analysisFailures.some((item) => ['anomalies', 'fingerprints', 'domino index', 'diffusion'].includes(item)) ? 'Some graph analyses are unavailable. Retry the analysis.' : null}
            anomalies={anomalyResults}
            fingerprints={fingerprints}
            dominoScores={dominoScores}
            diffusionResult={diffusionResult}
            isLoading={isRunning || isInitializing}
          />
        </section>
      </>
    )}
  </main>

      {/* Slide-in Facility Detail Drawer */}
      <FacilityDrawer
        facility={selectedFacilityObj}
        detail={facilityDetail?.scenario_id === scenario?.id && facilityDetail?.revision === scenario?.revision && facilityDetail?.sku_id === selectedSkuId ? facilityDetail : null}
        isLoading={isLoadingDetail}
        error={detailError}
        onRetry={() => setDetailAttempt((attempt) => attempt + 1)}
        onClose={() => setSelectedFacilityId(null)}
      />

      {/* Footer */}
      <footer className="border-t border-border/60 py-4 px-6 text-center text-xs text-muted-foreground bg-card/40 backdrop-blur-md">
        <p className="flex items-center justify-center gap-2 flex-wrap">
          <Sparkles className="size-3.5 text-primary" />
          <span>ShelfWatch Regional Contagion & Early-Warning Platform</span>
          <span>&bull;</span>
          <span>Manipal Hackathon 2026</span>
          <span>&bull;</span>
          <span>FEFO batch simulation &bull; Sampled donor reserve checks</span>
        </p>
      </footer>
    </div>
  );
}
