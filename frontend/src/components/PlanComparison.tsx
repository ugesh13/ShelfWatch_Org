import React from 'react';
import { motion } from 'framer-motion';
import { CheckCircle2, Shield, ArrowRight, Truck, ShieldAlert, Sparkles } from 'lucide-react';
import { PlanComparisonData } from '../lib/types';

interface PlanComparisonProps {
  planData: PlanComparisonData | null;
  isLoading: boolean;
  onApprovePlan: (planId: string) => void;
  onRejectPlan: (planId: string) => void;
  isReviewing: boolean;
  error: string | null;
}

export const PlanComparison: React.FC<PlanComparisonProps> = ({
  planData,
  isLoading,
  onApprovePlan,
  onRejectPlan,
  isReviewing,
  error,
}) => {
  if (isLoading) {
    return (
      <div className="bg-card/75 backdrop-blur-xl border border-white/[0.08] rounded-2xl p-6 shadow-xl flex flex-col items-center justify-center text-muted-foreground text-sm h-72 gap-3">
        <div className="size-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
        <span>Evaluating redistribution policies across sampled future paths…</span>
      </div>
    );
  }

  if (error || !planData) {
    return <p className="rounded-2xl border border-border bg-card p-6 text-sm text-muted-foreground">{error || 'Run a scenario to compare transfer plans.'}</p>;
  }

  const { comparison, selected_plan } = planData;
  const isApproved = selected_plan.status === 'APPROVED';
  const hasCoverage = selected_plan.modeled_facility_count > 0;
  const constraintsPassed = ['conservation_holds', 'donor_reserves_respected', 'zero_donor_harm_paths']
    .every((check) => selected_plan.constraint_checks[check] === true);
  const showMetric = (value: number) => hasCoverage ? value : 'Unknown';

  return (
    <div data-testid="plan-comparison" data-sku-id={selected_plan.sku_id} className="bg-card/75 backdrop-blur-xl border border-white/[0.08] rounded-2xl p-6 shadow-xl space-y-6">
      {/* Policy Comparison Table / Cards */}
      <div>
        <div className="flex items-center justify-between mb-4 border-b border-border/80 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="size-8 rounded-xl bg-emerald-500/20 border border-emerald-500/40 text-emerald-400 flex items-center justify-center shadow-inner">
              <Shield className="size-4" />
            </div>
            <div>
              <h3 className="text-sm font-extrabold text-white tracking-tight">
                Multi-Policy Counterfactual Comparison
              </h3>
              <p className="text-[11px] text-muted-foreground">Evaluating 3 allocation strategies on identical demand paths</p>
            </div>
          </div>
          <span className="text-[10px] px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 font-mono font-bold border border-emerald-500/30 flex items-center gap-1">
            <Sparkles className="size-3" />
            {!hasCoverage ? 'NO MODELED FACILITIES' : constraintsPassed ? 'SAMPLED DONOR CHECKS PASSED' : 'CONSTRAINT REVIEW REQUIRED'}
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5">
          {/* Policy A: No Action */}
          <motion.div
            whileHover={{ y: -2 }}
            className="bg-secondary/35 border border-border/70 rounded-xl p-4 text-xs flex flex-col justify-between transition-all"
          >
            <div>
              <div className="flex justify-between items-center text-[10px] uppercase font-bold text-muted-foreground">
                <span>Policy A</span>
                <span className="text-rose-400">Baseline Deficit</span>
              </div>
              <div className="font-extrabold text-white text-sm mt-1">No Intervention</div>
              <div className="mt-3 text-rose-400 text-2xl font-black">
                {showMetric(comparison.no_action.metrics.expected_unmet_units)}{' '}
                <span className="text-xs font-normal text-muted-foreground">unmet units</span>
              </div>
            </div>
            <div className="mt-3 pt-2.5 border-t border-border/50 text-[11px] text-muted-foreground font-medium">
              {showMetric(comparison.no_action.metrics.expected_facility_days)} clinic-days with unmet demand
            </div>
          </motion.div>

          {/* Policy B: Nearest Donor */}
          <motion.div
            whileHover={{ y: -2 }}
            className="bg-secondary/35 border border-border/70 rounded-xl p-4 text-xs flex flex-col justify-between transition-all"
          >
            <div>
              <div className="flex justify-between items-center text-[10px] uppercase font-bold text-muted-foreground">
                <span>Policy B</span>
                <span className="text-amber-400">Distance Priority</span>
              </div>
              <div className="font-extrabold text-white text-sm mt-1">Nearest Eligible Donor</div>
              <div className="mt-3 text-amber-400 text-2xl font-black">
                {showMetric(comparison.nearest_donor.metrics.expected_unmet_units)}{' '}
                <span className="text-xs font-normal text-muted-foreground">unmet units</span>
              </div>
            </div>
            <div className="mt-3 pt-2.5 border-t border-border/50 text-[11px] text-muted-foreground font-medium">
              Distance-first &bull; Same donor reserve checks
            </div>
          </motion.div>

          {/* Policy C: ShelfWatch */}
          <motion.div
            whileHover={{ y: -2 }}
            className="bg-gradient-to-br from-emerald-950/40 to-slate-900 border border-emerald-500/50 rounded-xl p-4 text-xs flex flex-col justify-between shadow-[0_0_25px_-5px_rgba(16,185,129,0.25)] relative overflow-hidden"
          >
            <div className="absolute top-0 right-0 size-16 bg-emerald-500/10 rounded-full blur-xl pointer-events-none" />
            <div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase font-black tracking-wider text-emerald-400">
                  Policy C &bull; ShelfWatch
                </span>
                <span className="text-[9px] px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 font-extrabold border border-emerald-500/40">
                  GREEDY
                </span>
              </div>
              <div className="font-extrabold text-white text-sm mt-1">Donor-Safe Optimization</div>
              <div className="mt-3 text-emerald-400 text-2xl font-black">
                {showMetric(comparison.shelfwatch.metrics.expected_unmet_units)}{' '}
                <span className="text-xs font-normal text-emerald-300/80">unmet units</span>
              </div>
            </div>
            <div className="mt-3 pt-2.5 border-t border-emerald-500/30 text-[11px] text-emerald-300 font-bold flex items-center gap-1">
              <CheckCircle2 className="size-3.5 text-emerald-400" />
              <span>{constraintsPassed ? 'No additional donor shortfall in sampled paths' : 'Constraints require review'}</span>
            </div>
          </motion.div>
        </div>
      </div>

      {/* Planned Transfers List */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-xs uppercase font-extrabold text-foreground tracking-wider flex items-center gap-2">
            <Truck className="size-4 text-primary" />
            <span>Recommended Batch-FEFO Stock Transfers ({selected_plan.transfers.length})</span>
          </h4>
          <span className="text-xs text-muted-foreground font-mono">
            Total Relocated: <span className="font-extrabold text-white">{selected_plan.metrics.transfer_units} units</span>
          </span>
        </div>

        <div className="space-y-2.5">
          {selected_plan.recommendations.map((rec) => (
            <motion.div
              key={rec.id}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              className="p-3.5 bg-secondary/35 border border-border/70 rounded-xl text-xs flex flex-wrap items-center justify-between gap-3 hover:border-border transition-all"
            >
              <div className="flex items-center gap-3">
                <div className="size-9 rounded-xl bg-emerald-500/20 border border-emerald-500/30 text-emerald-400 flex items-center justify-center font-bold shrink-0">
                  <ArrowRight className="size-4" />
                </div>
                <div>
                  <div className="flex items-center gap-2 font-black text-white text-sm">
                    <span className="text-emerald-300">Donor: {rec.from_facility_id}</span>
                    <ArrowRight className="size-3.5 text-muted-foreground" />
                    <span className="text-blue-300">Recipient: {rec.to_facility_id}</span>
                  </div>
                  <div className="text-[11px] text-muted-foreground mt-0.5 flex items-center gap-2">
                    <span>Route: <b className="font-mono text-slate-300">{rec.route_id}</b></span>
                    <span>&bull;</span>
                    <span>Dispatch: Day {rec.dispatch_day} &rarr; Arrives: Day {rec.arrival_day}</span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-6 text-right">
                <div>
                  <div className="text-[10px] text-muted-foreground uppercase font-bold tracking-wider">
                    Allocation
                  </div>
                  <div className="text-lg font-black text-emerald-400">+{rec.quantity_units} units</div>
                </div>

                <div className="border-l border-border/80 pl-4 text-left">
                  <div className="text-[10px] text-muted-foreground uppercase font-bold tracking-wider">
                    Donor reserve check
                  </div>
                  <div className="text-xs font-mono font-bold text-white mt-0.5">
                    Tightest reserve margin: <b>{rec.donor_minimum_planning_stock}u</b> &ge; <b>{rec.donor_reserve_at_minimum_day}u</b> (7d)
                  </div>
                  <div className="text-[10px] text-emerald-400 font-semibold mt-0.5">
                    &bull; {rec.sampled_donor_harm_paths} paths with added donor shortfall
                  </div>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      </div>

      {hasCoverage && selected_plan.metrics.expected_unmet_units > 0 && (
        <p className="rounded-xl border border-amber-500/40 bg-amber-950/30 p-3 text-xs text-amber-200">
          Remaining expected deficit: {selected_plan.metrics.expected_unmet_units} units over 14 days. Additional replenishment is required.
        </p>
      )}
      {selected_plan.transfers.length === 0 && <p className="text-sm text-muted-foreground">No beneficial eligible transfers were found.</p>}
      <ul className="space-y-1 text-xs text-muted-foreground list-disc pl-4">
        {selected_plan.notes.map((note) => <li key={note}>{note}</li>)}
      </ul>

      {/* Audit Review Actions */}
      <div className="pt-4 border-t border-border/80 flex flex-wrap items-center justify-between gap-4">
        <div className="text-xs text-muted-foreground max-w-[420px]">
          {isApproved ? (
            <span className="text-emerald-300 font-semibold flex items-center gap-2">
              <CheckCircle2 className="size-4 text-emerald-400 shrink-0" />
              Plan Approved and recorded in immutable scenario review audit log.
            </span>
          ) : (
            <span className="flex items-center gap-1.5">
              <ShieldAlert className="size-3.5 text-muted-foreground shrink-0" />
              Approval records a simulated proposal. Physical stock is not dispatched.
            </span>
          )}
        </div>

        {!isApproved ? (
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={() => onApprovePlan(selected_plan.id)}
            disabled={isReviewing || !constraintsPassed || selected_plan.transfers.length === 0}
            className="bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-extrabold text-xs px-6 py-3 rounded-xl transition-all shadow-lg shadow-emerald-500/25 flex items-center gap-2.5 cursor-pointer disabled:opacity-50 border border-emerald-400/30"
          >
            <CheckCircle2 className="size-4" />
            <span>{isReviewing ? 'Logging Review...' : 'Approve Plan'}</span>
          </motion.button>
        ) : (
          <span className="px-4 py-2 bg-emerald-500/20 text-emerald-300 font-mono font-bold text-xs rounded-xl border border-emerald-500/40 shadow-inner flex items-center gap-2">
            <CheckCircle2 className="size-3.5 text-emerald-400" />
            AUDIT STATUS: APPROVED
          </span>
        )}
        {selected_plan.status !== 'REJECTED' && selected_plan.transfers.length > 0 && (
          <button onClick={() => onRejectPlan(selected_plan.id)} disabled={isReviewing}
            className="rounded-xl border border-border px-4 py-2 text-xs text-rose-300 disabled:opacity-50">
            Reject Plan
          </button>
        )}
        {selected_plan.status === 'REJECTED' && <span className="text-xs text-rose-300">Review status: rejected</span>}
      </div>
    </div>
  );
};
