import { motion, AnimatePresence } from 'framer-motion';
import {
  Fingerprint,
  Network,
  Radiation,
  TrendingUp,
  AlertTriangle,
  ShieldAlert,
  Clock,
  Zap,
  Activity,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { useState } from 'react';
import type {
  AnomalyResult,
  Fingerprint as FingerprintType,
  DominoScore,
  DiffusionResult,
  ShortageType,
  RiskLevel,
} from '../lib/types';

// ── Color/Label Maps ─────────────────────────────────────────────────────────
const SHORTAGE_COLORS: Record<ShortageType, string> = {
  DEMAND_SURGE: 'from-orange-500 to-amber-500',
  SUPPLY_DISRUPTION: 'from-red-500 to-rose-500',
  PANIC_HOARDING: 'from-purple-500 to-fuchsia-500',
  CHRONIC_EROSION: 'from-slate-500 to-zinc-500',
  MIXED: 'from-blue-500 to-indigo-500',
};

const SHORTAGE_LABELS: Record<ShortageType, string> = {
  DEMAND_SURGE: 'Demand Surge',
  SUPPLY_DISRUPTION: 'Supply Disruption',
  PANIC_HOARDING: 'Isolated demand spike',
  CHRONIC_EROSION: 'Chronic Erosion',
  MIXED: 'Mixed / Unknown',
};

const SHORTAGE_ICONS: Record<ShortageType, typeof TrendingUp> = {
  DEMAND_SURGE: TrendingUp,
  SUPPLY_DISRUPTION: Clock,
  PANIC_HOARDING: ShieldAlert,
  CHRONIC_EROSION: Activity,
  MIXED: Zap,
};

const RISK_COLORS: Record<RiskLevel, string> = {
  STABLE: 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30',
  AT_RISK: 'text-amber-400 bg-amber-500/15 border-amber-500/30',
  CRITICAL: 'text-rose-400 bg-rose-500/15 border-rose-500/30',
  STOCKOUT: 'text-red-300 bg-red-500/20 border-red-500/40',
  UNKNOWN: 'text-slate-300 bg-slate-500/15 border-slate-500/30',
};

// ── Sub-components ───────────────────────────────────────────────────────────

function FingerprintBadge({ fp }: { fp: FingerprintType }) {
  const Icon = SHORTAGE_ICONS[fp.shortage_type];
  const gradient = SHORTAGE_COLORS[fp.shortage_type];
  const label = SHORTAGE_LABELS[fp.shortage_type];

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      className="flex items-center gap-2.5 bg-card/80 border border-white/[0.08] rounded-xl px-3 py-2.5 hover:border-white/[0.15] transition-all group"
    >
      <div className={`size-8 rounded-lg bg-gradient-to-br ${gradient} flex items-center justify-center shadow-lg`}>
        <Icon className="size-4 text-white" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-bold text-white truncate">{fp.facility_id}</span>
          <span className={`text-[9px] font-black uppercase px-1.5 py-0.5 rounded bg-gradient-to-r ${gradient} text-white`}>
            {label}
          </span>
        </div>
        <p className="text-[10px] text-muted-foreground truncate mt-0.5">
          {fp.recommended_intervention.slice(0, 80)}…
        </p>
      </div>
      <div className="text-right shrink-0">
        <div className="text-sm font-black text-white">{fp.rule_score.toFixed(2)}</div>
        <div className="text-[9px] text-muted-foreground">rule score / 1</div>
      </div>
    </motion.div>
  );
}

function DominoBar({ score, maxIndex }: { score: DominoScore; maxIndex: number }) {
  const widthPct = maxIndex > 0 && score.domino_index !== null ? (score.domino_index / maxIndex) * 100 : 0;
  const dangerLevel = score.domino_index === null ? 'unknown' : score.domino_index >= 5 ? 'rose' : score.domino_index >= 3 ? 'amber' : 'emerald';

  return (
    <div className="flex items-center gap-3 py-1.5">
      <span className="text-[10px] font-bold text-white w-12 shrink-0 truncate">{score.facility_id}</span>
      <div className="flex-1 h-5 bg-slate-800/80 rounded-full overflow-hidden relative border border-white/[0.05]">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${widthPct}%` }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
          className={`h-full rounded-full bg-gradient-to-r ${
            dangerLevel === 'rose'
              ? 'from-rose-600 to-rose-400'
              : dangerLevel === 'amber'
              ? 'from-amber-600 to-amber-400'
              : 'from-emerald-600 to-emerald-400'
          } shadow-[0_0_12px_-3px_var(--tw-shadow-color)]`}
          style={{
            '--tw-shadow-color': dangerLevel === 'rose' ? '#f43f5e' : dangerLevel === 'amber' ? '#f59e0b' : '#10b981',
          } as React.CSSProperties}
        />
        <span className="absolute inset-y-0 left-2 flex items-center text-[10px] font-black text-white/90 drop-shadow">
          {score.domino_index ?? 'Unknown'}
        </span>
      </div>
      <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${RISK_COLORS[dangerLevel === 'unknown' ? 'UNKNOWN' : dangerLevel === 'rose' ? 'CRITICAL' : dangerLevel === 'amber' ? 'AT_RISK' : 'STABLE']}`}>
        #{score.vulnerability_rank}
      </span>
    </div>
  );
}

function DiffusionTimeline({ timeline }: { timeline: DiffusionResult['timeline'] }) {
  if (!timeline.length) return null;
  const maxFacilities = Math.max(1, ...timeline.map((point) =>
    point.facilities_stable + point.facilities_at_risk + point.facilities_critical + point.facilities_unknown));
  const height = 90;
  const scale = height / maxFacilities;

  return (
    <div className="w-full">
      <svg role="img" aria-label="Daily facility counts by heuristic graph risk category"
        width="100%" height={height} viewBox={'0 0 ' + timeline.length * 24 + ' ' + height} preserveAspectRatio="none">
        {timeline.map((point, index) => {
          const critical = point.facilities_critical * scale;
          const atRisk = point.facilities_at_risk * scale;
          const stable = point.facilities_stable * scale;
          const unknown = point.facilities_unknown * scale;
          return <g key={point.day}>
            <title>{'Day ' + point.day + ': ' + point.facilities_critical + ' critical, ' + point.facilities_at_risk + ' at risk, ' + point.facilities_stable + ' stable, ' + point.facilities_unknown + ' unknown'}</title>
            <rect x={index * 24} y={height - critical} width={21} height={critical} fill="#ef4444" />
            <rect x={index * 24} y={height - critical - atRisk} width={21} height={atRisk} fill="#eab308" />
            <rect x={index * 24} y={height - critical - atRisk - stable} width={21} height={stable} fill="#22c55e" />
            <rect x={index * 24} y={height - critical - atRisk - stable - unknown} width={21} height={unknown} fill="#94a3b8" />
          </g>;
        })}
      </svg>
      <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
        <span>Day {timeline[0].day}</span><span>Day {timeline[timeline.length - 1].day}</span>
      </div>
      <p className="text-[10px] text-muted-foreground mt-2">Red: critical · Amber: at risk · Green: stable · Gray: unknown</p>
    </div>
  );
}

// ── Main Component ───────────────────────────────────────────────────────────
interface ContagionPanelProps {
  anomalies: AnomalyResult[];
  fingerprints: FingerprintType[];
  dominoScores: DominoScore[];
  diffusionResult: DiffusionResult | null;
  isLoading: boolean;
  error: string | null;
}

export function ContagionPanel({
  anomalies,
  fingerprints,
  dominoScores,
  diffusionResult,
  isLoading,
  error,
}: ContagionPanelProps) {
  const [expandedSection, setExpandedSection] = useState<string | null>('fingerprints');

  // Derived stats
  const criticalCount = anomalies.filter((a) => a.risk_level === 'CRITICAL' || a.risk_level === 'STOCKOUT').length;
  const atRiskCount = anomalies.filter((a) => a.risk_level === 'AT_RISK').length;
  const topDomino = dominoScores.length > 0 ? dominoScores[0] : null;
  const maxDomino = Math.max(1, ...dominoScores.map((score) => score.domino_index ?? 0));
  const lastDiffDay = diffusionResult?.timeline?.slice(-1)[0] ?? null;
  const regionalRisk = lastDiffDay?.regional_risk_score;
  const unknownCount = anomalies.filter((anomaly) => anomaly.risk_level === 'UNKNOWN').length;

  // Shortage type distribution for mini chart
  const typeDistribution: Record<string, number> = {};
  for (const fp of fingerprints) {
    typeDistribution[fp.shortage_type] = (typeDistribution[fp.shortage_type] || 0) + 1;
  }

  const toggleSection = (section: string) => {
    setExpandedSection((prev) => (prev === section ? null : section));
  };

  if (isLoading) {
    return (
      <div className="bg-card/60 backdrop-blur-xl border border-white/[0.08] rounded-2xl p-6 shadow-2xl">
        <div className="flex items-center gap-3">
          <div className="size-10 rounded-xl bg-primary/15 border border-primary/30 flex items-center justify-center">
            <Radiation className="size-5 text-primary animate-pulse" />
          </div>
          <div>
            <h3 className="text-sm font-extrabold text-white">Experimental graph analysis</h3>
            <p className="text-[10px] text-muted-foreground">Computing heuristic scores…</p>
          </div>
        </div>
        <div className="mt-4 space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-10 bg-slate-800/50 rounded-xl animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.1 }}
      className="bg-card/60 backdrop-blur-xl border border-white/[0.08] rounded-2xl shadow-2xl overflow-hidden"
    >
      {/* Header */}
      <div className="px-5 pt-5 pb-4 border-b border-white/[0.06]">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="size-10 rounded-xl bg-gradient-to-br from-violet-500/20 to-fuchsia-500/20 border border-violet-500/30 flex items-center justify-center shadow-inner">
              <Radiation className="size-5 text-violet-400" />
            </div>
            <div>
              <h3 className="text-sm font-extrabold text-white tracking-tight">Experimental graph analysis</h3>
              <p className="text-[10px] text-muted-foreground">Domino index · Pattern rules · Graph diffusion</p>
            </div>
          </div>
          {/* Mini stats */}
          <div className="flex gap-3">
            <div className="text-center">
              <div className="text-lg font-black text-rose-400">{anomalies.length > unknownCount ? criticalCount : '—'}</div>
              <div className="text-[8px] text-muted-foreground uppercase font-bold">Critical</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-black text-amber-400">{anomalies.length > unknownCount ? atRiskCount : '—'}</div>
              <div className="text-[8px] text-muted-foreground uppercase font-bold">At Risk</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-black text-violet-400">{regionalRisk == null ? 'Unknown' : regionalRisk.toFixed(2)}</div>
              <div className="text-[8px] text-muted-foreground uppercase font-bold">Graph score / 1</div>
            </div>
          </div>
        </div>
        <p className="text-[11px] text-muted-foreground mt-3">These rule and graph scores are uncalibrated heuristics. They are not shortage probabilities or confirmed causes.{unknownCount > 0 ? ` ${unknownCount} facilities have insufficient evidence.` : ''}</p>
        {error && <p className="mt-2 text-xs text-amber-300">{error}</p>}
      </div>

      {/* Section: Shortage Fingerprints */}
      <div className="border-b border-white/[0.04]">
        <button
          onClick={() => toggleSection('fingerprints')}
          aria-expanded={expandedSection === 'fingerprints'}
          aria-controls="fingerprint-section"
          className="w-full px-5 py-3.5 flex items-center justify-between hover:bg-white/[0.02] transition-colors cursor-pointer"
        >
          <div className="flex items-center gap-2.5">
            <Fingerprint className="size-4 text-fuchsia-400" />
            <span className="text-xs font-bold text-white">Shortage Fingerprints</span>
            <span className="text-[9px] text-muted-foreground bg-white/[0.06] px-1.5 py-0.5 rounded-full font-bold">
              {fingerprints.length} classified
            </span>
          </div>
          {expandedSection === 'fingerprints' ? (
            <ChevronUp className="size-4 text-muted-foreground" />
          ) : (
            <ChevronDown className="size-4 text-muted-foreground" />
          )}
        </button>
        <AnimatePresence>
          {expandedSection === 'fingerprints' && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div id="fingerprint-section" className="px-5 pb-4 space-y-2">
                {fingerprints.length === 0 ? (
                  <p className="text-[11px] text-muted-foreground py-3 text-center">{error ? 'Pattern results may be unavailable.' : 'No classified patterns in facilities with sufficient evidence.'}</p>
                ) : (
                  <>
                    {/* Type distribution mini badges */}
                    <div className="flex flex-wrap gap-1.5 mb-3">
                      {Object.entries(typeDistribution).map(([type, count]) => (
                        <span
                          key={type}
                          className={`text-[9px] font-bold uppercase px-2 py-1 rounded-full bg-gradient-to-r ${
                            SHORTAGE_COLORS[type as ShortageType]
                          } text-white shadow-sm`}
                        >
                          {SHORTAGE_LABELS[type as ShortageType]} × {count}
                        </span>
                      ))}
                    </div>
                    {fingerprints.slice(0, 6).map((fp) => (
                      <FingerprintBadge key={fp.facility_id} fp={fp} />
                    ))}
                    {fingerprints.length > 6 && (
                      <p className="text-[10px] text-muted-foreground text-center py-1">
                        +{fingerprints.length - 6} more classified
                      </p>
                    )}
                  </>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Section: Domino Index */}
      <div className="border-b border-white/[0.04]">
        <button
          onClick={() => toggleSection('domino')}
          aria-expanded={expandedSection === 'domino'}
          aria-controls="domino-section"
          className="w-full px-5 py-3.5 flex items-center justify-between hover:bg-white/[0.02] transition-colors cursor-pointer"
        >
          <div className="flex items-center gap-2.5">
            <Network className="size-4 text-orange-400" />
            <span className="text-xs font-bold text-white">Domino Index</span>
            {topDomino?.domino_index != null && (
              <span className="text-[9px] text-muted-foreground bg-white/[0.06] px-1.5 py-0.5 rounded-full font-bold">
                Top: {topDomino.facility_id} → {topDomino.domino_index} simulated cascades
              </span>
            )}
          </div>
          {expandedSection === 'domino' ? (
            <ChevronUp className="size-4 text-muted-foreground" />
          ) : (
            <ChevronDown className="size-4 text-muted-foreground" />
          )}
        </button>
        <AnimatePresence>
          {expandedSection === 'domino' && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div id="domino-section" className="px-5 pb-4 space-y-0.5">
                {dominoScores.length === 0 && <p className="text-xs text-muted-foreground">Domino estimates unavailable.</p>}
                {dominoScores.slice(0, 8).map((score) => (
                  <DominoBar key={score.facility_id} score={score} maxIndex={maxDomino} />
                ))}
                {topDomino && (
                  <p className="text-[10px] text-muted-foreground mt-2 leading-relaxed border-t border-white/[0.04] pt-2">
                    {topDomino.risk_narrative}
                  </p>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Section: SIS Diffusion Cascade */}
      <div>
        <button
          onClick={() => toggleSection('diffusion')}
          aria-expanded={expandedSection === 'diffusion'}
          aria-controls="diffusion-section"
          className="w-full px-5 py-3.5 flex items-center justify-between hover:bg-white/[0.02] transition-colors cursor-pointer"
        >
          <div className="flex items-center gap-2.5">
            <AlertTriangle className="size-4 text-rose-400" />
            <span className="text-xs font-bold text-white">Experimental graph diffusion</span>
            {lastDiffDay && (
              <span className="text-[9px] text-muted-foreground bg-white/[0.06] px-1.5 py-0.5 rounded-full font-bold">
                Day {lastDiffDay.day}: {lastDiffDay.facilities_critical} critical
              </span>
            )}
          </div>
          {expandedSection === 'diffusion' ? (
            <ChevronUp className="size-4 text-muted-foreground" />
          ) : (
            <ChevronDown className="size-4 text-muted-foreground" />
          )}
        </button>
        <AnimatePresence>
          {expandedSection === 'diffusion' && !diffusionResult && <p id="diffusion-section" className="px-5 pb-4 text-xs text-muted-foreground">Graph diffusion unavailable.</p>}
          {expandedSection === 'diffusion' && diffusionResult && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div id="diffusion-section" className="px-5 pb-5">
                <DiffusionTimeline timeline={diffusionResult.timeline} />
                <div className="grid grid-cols-3 gap-3 mt-3">
                  <div className="text-center p-2 rounded-lg bg-emerald-950/30 border border-emerald-500/20">
                    <div className="text-sm font-black text-emerald-400">
                      {diffusionResult.timeline[0]?.facilities_stable ?? '—'}
                    </div>
                    <div className="text-[8px] text-muted-foreground uppercase font-bold">Stable (Day {diffusionResult.timeline[0]?.day})</div>
                  </div>
                  <div className="text-center p-2 rounded-lg bg-amber-950/30 border border-amber-500/20">
                    <div className="text-sm font-black text-amber-400">
                      {lastDiffDay?.facilities_at_risk ?? '—'}
                    </div>
                    <div className="text-[8px] text-muted-foreground uppercase font-bold">At-Risk (Day {lastDiffDay?.day})</div>
                  </div>
                  <div className="text-center p-2 rounded-lg bg-rose-950/30 border border-rose-500/20">
                    <div className="text-sm font-black text-rose-400">
                      {lastDiffDay?.facilities_critical ?? '—'}
                    </div>
                    <div className="text-[8px] text-muted-foreground uppercase font-bold">Critical (Day {lastDiffDay?.day})</div>
                  </div>
                </div>
                {(lastDiffDay?.facilities_unknown ?? 0) > 0 && <p className="text-xs text-muted-foreground mt-3">{lastDiffDay?.facilities_unknown} facilities remain unknown and are excluded from the regional graph score.</p>}
                <ul className="mt-3 text-[11px] text-muted-foreground list-disc pl-4 space-y-1">{diffusionResult.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
