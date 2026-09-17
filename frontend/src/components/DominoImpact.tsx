import React from 'react';
import { motion } from 'framer-motion';
import { Zap, AlertTriangle, ShieldCheck } from 'lucide-react';
import { DominoImpactResult } from '../lib/types';

interface DominoImpactProps {
  impactResults: DominoImpactResult[];
  isLoading: boolean;
  error: string | null;
}

export const DominoImpact: React.FC<DominoImpactProps> = ({ impactResults, isLoading, error }) => {
  if (error) return <p className="rounded-2xl border border-border p-5 text-sm text-muted-foreground">{error}</p>;
  return (
    <div className="bg-card/75 backdrop-blur-xl border border-white/[0.08] rounded-2xl p-5 shadow-xl flex flex-col justify-between space-y-4">
      <div>
        <div className="flex items-center justify-between mb-4 border-b border-border/80 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="size-8 rounded-xl bg-amber-500/20 border border-amber-500/40 text-amber-400 flex items-center justify-center shadow-inner">
              <Zap className="size-4 text-amber-400 animate-pulse" />
            </div>
            <div>
              <h3 className="text-sm font-extrabold text-white tracking-tight">Domino Depot Vulnerability</h3>
              <p className="text-[11px] text-muted-foreground">Paired +7d counterfactual failure shocks</p>
            </div>
          </div>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-300 font-mono font-bold border border-amber-500/30">
            SYSTEMIC VULNERABILITY
          </span>
        </div>

        {isLoading ? (
          <div className="h-36 flex flex-col items-center justify-center gap-2 text-xs text-muted-foreground">
            <div className="size-6 border-2 border-amber-500 border-t-transparent rounded-full animate-spin" />
            <span>Calculating paired counterfactuals...</span>
          </div>
        ) : (
          <div className="space-y-3">
            {impactResults.map((depot, idx) => {
              const isHighImpact = depot.additional_unmet_units_mean > 0;
              return (
                <motion.div
                  key={depot.depot_id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: idx * 0.1 }}
                  className={`p-3.5 rounded-xl border text-xs transition-all ${
                    isHighImpact
                      ? 'bg-rose-950/25 border-rose-500/40 shadow-[0_0_20px_-5px_rgba(244,63,94,0.2)]'
                      : 'bg-secondary/40 border-border/60 hover:border-border'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-extrabold text-white text-sm">{depot.depot_name}</span>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-muted border border-border text-muted-foreground font-semibold">
                        {depot.depot_id}
                      </span>
                    </div>
                    <span className="text-[10px] font-bold text-muted-foreground font-mono">
                      Impact Rank #{idx + 1}
                    </span>
                  </div>

                  <div className="grid grid-cols-2 gap-3 mt-2.5 pt-2.5 border-t border-border/50">
                    <div>
                      <div className="text-[10px] text-muted-foreground uppercase font-bold tracking-wider">
                        Added Facility Shortages
                      </div>
                      <div className="text-lg font-black text-white mt-0.5">
                        {depot.modeled_facility_count ? `+${depot.additional_affected_facilities_mean}` : 'Unknown'}{' '}
                        <span className="text-[11px] font-normal text-muted-foreground">clinics</span>
                      </div>
                    </div>

                    <div>
                      <div className="text-[10px] text-muted-foreground uppercase font-bold tracking-wider">
                        Regional Deficit Shock
                      </div>
                      <div
                        className={`text-lg font-black mt-0.5 ${
                          isHighImpact ? 'text-rose-400' : 'text-emerald-400'
                        }`}
                      >
                        {depot.modeled_facility_count ? `+${depot.additional_unmet_units_mean}` : 'Unknown'}{' '}
                        <span className="text-[11px] font-normal text-muted-foreground">units</span>
                      </div>
                    </div>
                  </div>

                  {depot.newly_affected_facility_ids.length > 0 ? (
                    <div className="mt-2.5 p-2 rounded-lg bg-rose-500/10 border border-rose-500/20 text-[11px] text-rose-300 flex items-center gap-1.5 font-medium">
                      <AlertTriangle className="size-3.5 shrink-0 text-rose-400" />
                      <span>Cascades to facilities: <b>{depot.newly_affected_facility_ids.join(', ')}</b></span>
                    </div>
                  ) : (
                    <div className="mt-2 text-[10px] text-muted-foreground flex items-center gap-1">
                      <ShieldCheck className="size-3.5 text-emerald-400" />
                      <span>{depot.modeled_facility_count === 0 ? 'Insufficient evidence for this comparison.' : isHighImpact ? 'Existing shortages worsen; no additional facility is newly affected.' : 'No additional shortage within the tested horizon.'}</span>
                    </div>
                  )}
                  <p className="mt-2 text-[11px] text-muted-foreground">
                    {depot.horizon_days}-day horizon · +{depot.tested_extra_days} days to pending receipts · P10–P90 added unmet units: {depot.additional_unmet_units_p10}–{depot.additional_unmet_units_p90}.
                    {depot.excluded_facility_ids.length > 0 && ` Excludes ${depot.excluded_facility_ids.length} facilities with insufficient evidence.`}
                  </p>
                </motion.div>
              );
            })}
          </div>
        )}
      </div>

      <div className="pt-3 border-t border-border/80 text-[11px] text-muted-foreground leading-relaxed">
        Paired counterfactual experiments compute exact delta in unmet units across identical demand paths when a supplier hub is delayed by 7 days.
      </div>
    </div>
  );
};
