import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Sliders, RefreshCw, Lock, Sparkles } from 'lucide-react';
import { Assumptions } from '../lib/types';

interface ScenarioControlsProps {
  currentAssumptions: Assumptions;
  onApplyPatch: (newAssumptions: Assumptions) => void;
  isUpdating: boolean;
  targetFacilityId?: string;
  targetRouteId?: string;
  selectedSkuId?: string;
}

export const ScenarioControls: React.FC<ScenarioControlsProps> = ({
  currentAssumptions,
  onApplyPatch,
  isUpdating,
  targetFacilityId,
  targetRouteId,
  selectedSkuId,
}) => {
  const activeFacilityId = targetFacilityId || 'F-A';
  const activeSku = selectedSkuId || 'AMX500_CAP';
  const activeRouteId = targetRouteId || 'B_TO_A';
  const controlledOverride = currentAssumptions.demand_overrides.find(
    (override) => override.facility_id === activeFacilityId && override.sku_id === activeSku
  );
  // Find current depot delay for DEPOT-N and DEPOT-S
  const initialDepotNDelay =
    currentAssumptions.depot_delays.find((d) => d.depot_id === 'DEPOT-N')?.extra_days || 0;
  const initialDepotSDelay =
    currentAssumptions.depot_delays.find((d) => d.depot_id === 'DEPOT-S')?.extra_days || 0;
  const initialDemandMult =
    controlledOverride?.multiplier ?? 1.0;
  const initialClosedRoute = currentAssumptions.closed_route_ids.includes(activeRouteId);

  const [depotNDelay, setDepotNDelay] = useState(initialDepotNDelay);
  const [depotSDelay, setDepotSDelay] = useState(initialDepotSDelay);
  const [demandMult, setDemandMult] = useState(initialDemandMult);
  const [routeClosed, setRouteClosed] = useState(initialClosedRoute);

  // Sync state whenever active scenario preset or external assumptions change
  useEffect(() => {
    const nDelay = currentAssumptions.depot_delays.find((d) => d.depot_id === 'DEPOT-N')?.extra_days || 0;
    const sDelay = currentAssumptions.depot_delays.find((d) => d.depot_id === 'DEPOT-S')?.extra_days || 0;
    const dMult = currentAssumptions.demand_overrides.find(
      (override) => override.facility_id === activeFacilityId && override.sku_id === activeSku
    )?.multiplier ?? 1.0;
    const rClosed = currentAssumptions.closed_route_ids.includes(activeRouteId);

    setDepotNDelay(nDelay);
    setDepotSDelay(sDelay);
    setDemandMult(dMult);
    setRouteClosed(rClosed);
  }, [currentAssumptions, activeFacilityId, activeSku, activeRouteId]);

  const handleApply = () => {
    const delays = currentAssumptions.depot_delays.filter((delay) => !['DEPOT-N', 'DEPOT-S'].includes(delay.depot_id));
    if (depotNDelay > 0) delays.push({ depot_id: 'DEPOT-N', extra_days: depotNDelay });
    if (depotSDelay > 0) delays.push({ depot_id: 'DEPOT-S', extra_days: depotSDelay });

    const overrides = currentAssumptions.demand_overrides.filter((override) => override !== controlledOverride);
    if (demandMult !== 1.0) {
      overrides.push({
        facility_id: activeFacilityId,
        sku_id: activeSku,
        multiplier: demandMult,
        start_day: controlledOverride?.start_day ?? 0,
        end_day: controlledOverride?.end_day ?? 13,
      });
    }

    const closed = currentAssumptions.closed_route_ids.filter((routeId) => routeId !== activeRouteId);
    if (routeClosed) closed.push(activeRouteId);

    onApplyPatch({
      depot_delays: delays,
      demand_overrides: overrides,
      closed_route_ids: closed,
    });
  };

  return (
    <div className="bg-card/75 backdrop-blur-xl border border-white/[0.08] rounded-2xl p-5 shadow-xl flex flex-col justify-between space-y-4">
      <div>
        <div className="flex items-center justify-between mb-4 border-b border-border/80 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="size-8 rounded-xl bg-purple-500/20 border border-purple-500/40 text-purple-400 flex items-center justify-center shadow-inner">
              <Sliders className="size-4" />
            </div>
            <div>
              <h3 className="text-sm font-extrabold text-white tracking-tight">What-If Simulation Sandbox</h3>
              <p className="text-[11px] text-muted-foreground">Override supplier delays & demand surges</p>
            </div>
          </div>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-300 font-mono font-bold border border-purple-500/30">
            SHOCK INJECTION
          </span>
        </div>

        <div className="space-y-4">
          {/* Depot North Delay Slider */}
          <div className="p-3 rounded-xl bg-secondary/40 border border-border/50 space-y-1.5">
            <div className="flex justify-between text-xs items-center">
              <span className="text-foreground font-semibold flex items-center gap-1.5">
                <span className="size-2 rounded-full bg-amber-400"></span>
                North Depot Extra Delay
              </span>
              <span className="font-mono font-black text-amber-400 bg-amber-500/10 border border-amber-500/30 px-2 py-0.5 rounded">
                +{depotNDelay} days
              </span>
            </div>
            <input
              type="range"
              aria-label="North Depot Extra Delay"
              disabled={isUpdating}
              min={0}
              max={14}
              value={depotNDelay}
              onChange={(e) => setDepotNDelay(parseInt(e.target.value))}
              className="w-full h-2 bg-secondary rounded-lg appearance-none cursor-pointer accent-amber-400"
            />
            <div className="flex justify-between text-[10px] text-muted-foreground font-mono">
              <span>0d (On Time)</span>
              <span>+7d (Severe)</span>
              <span>+14d (Disrupted)</span>
            </div>
          </div>

          {/* Depot South Delay Slider */}
          <div className="p-3 rounded-xl bg-secondary/40 border border-border/50 space-y-1.5">
            <div className="flex justify-between text-xs items-center">
              <span className="text-foreground font-semibold flex items-center gap-1.5">
                <span className="size-2 rounded-full bg-blue-400"></span>
                South Depot Extra Delay
              </span>
              <span className="font-mono font-black text-blue-400 bg-blue-500/10 border border-blue-500/30 px-2 py-0.5 rounded">
                +{depotSDelay} days
              </span>
            </div>
            <input
              type="range"
              min={0}
              max={14}
              value={depotSDelay}
              aria-label="South Depot Extra Delay"
              disabled={isUpdating}
              onChange={(e) => setDepotSDelay(parseInt(e.target.value))}
              className="w-full h-2 bg-secondary rounded-lg appearance-none cursor-pointer accent-blue-400"
            />
            <div className="flex justify-between text-[10px] text-muted-foreground font-mono">
              <span>0d (On Time)</span>
              <span>+7d (Severe)</span>
              <span>+14d (Disrupted)</span>
            </div>
          </div>

          {/* Demand Surge Multiplier */}
          <div className="p-3 rounded-xl bg-secondary/40 border border-border/50 space-y-1.5">
            <div className="flex justify-between text-xs items-center">
              <span className="text-foreground font-semibold flex items-center gap-1.5">
                <span className="size-2 rounded-full bg-rose-400"></span>
                Demand Surge Multiplier ({activeFacilityId})
              </span>
              <span className="font-mono font-black text-rose-400 bg-rose-500/10 border border-rose-500/30 px-2 py-0.5 rounded">
                {demandMult.toFixed(1)}x
              </span>
            </div>
            <input
              type="range"
              min={0}
              max={3.0}
              step={0.5}
              value={demandMult}
              aria-label={`Demand multiplier for ${activeFacilityId}`}
              disabled={isUpdating}
              onChange={(e) => setDemandMult(parseFloat(e.target.value))}
              className="w-full h-2 bg-secondary rounded-lg appearance-none cursor-pointer accent-rose-400"
            />
            <div className="flex justify-between text-[10px] text-muted-foreground font-mono">
              <span>0x (No demand) · 1x normal</span>
              <span>2x (Double demand)</span>
              <span>3x (Triple demand)</span>
            </div>
          </div>

          {/* Route Closure Toggle */}
          <div className="p-3 rounded-xl bg-secondary/40 border border-border/50 flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="size-7 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 flex items-center justify-center">
                <Lock className="size-3.5" />
              </div>
              <div>
                <span className="text-xs font-bold text-white block">Cut Highway Transit Route</span>
                <span className="text-[10px] text-muted-foreground">Block primary donor transfer corridor ({activeRouteId})</span>
              </div>
            </div>
            <label className="relative inline-flex h-11 w-12 shrink-0 items-center justify-center cursor-pointer">
              <input
                type="checkbox"
                aria-label={`Close transfer route ${activeRouteId}`}
                disabled={isUpdating}
                checked={routeClosed}
                onChange={(e) => setRouteClosed(e.target.checked)}
                className="absolute inset-0 h-full w-full opacity-0 cursor-pointer peer"
              />
              <div className="relative pointer-events-none w-9 h-5 bg-secondary peer-focus-visible:ring-2 peer-focus-visible:ring-blue-300 rounded-full peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-rose-500"></div>
            </label>
          </div>
        </div>
      </div>

      <div className="pt-2">
        <motion.button
          whileHover={{ scale: 1.01 }}
          whileTap={{ scale: 0.99 }}
          onClick={handleApply}
          disabled={isUpdating}
          className="w-full bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white font-bold text-xs py-3 rounded-xl transition-all shadow-lg shadow-purple-600/20 flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50 border border-purple-400/30"
        >
          {isUpdating ? (
            <RefreshCw className="size-4 animate-spin" />
          ) : (
            <Sparkles className="size-4 text-purple-200" />
          )}
          <span>{isUpdating ? 'Recalculating Outcomes...' : 'Apply What-If & Re-simulate'}</span>
        </motion.button>
      </div>
    </div>
  );
};
