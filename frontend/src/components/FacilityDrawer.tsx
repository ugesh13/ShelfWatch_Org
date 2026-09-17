import { useEffect, useRef } from 'react';
import { X, AlertCircle, TrendingUp, Truck, Calendar, Clock } from 'lucide-react';
import {
  ResponsiveContainer, ComposedChart, Area, Line, XAxis, YAxis,
  Tooltip as RechartsTooltip, CartesianGrid, BarChart, Bar,
} from 'recharts';
import { Facility, FacilityDetailData, FacilityRiskSummary } from '../lib/types';

interface FacilityDrawerProps {
  facility: Facility | null;
  detail: FacilityDetailData | null;
  isLoading: boolean;
  error: string | null;
  onRetry: () => void;
  onClose: () => void;
}

const RISK_CLASSES: Record<FacilityRiskSummary['risk_state'], string> = {
  Empty: 'bg-rose-500/20 text-rose-300 border-rose-500/50',
  'High risk': 'bg-rose-500/20 text-rose-300 border-rose-500/50',
  Watch: 'bg-amber-500/20 text-amber-300 border-amber-500/50',
  'Lower risk': 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50',
  Unknown: 'bg-slate-500/20 text-slate-300 border-slate-500/50',
};

const TOOLTIP_STYLE = {
  backgroundColor: '#0f172a', borderColor: 'rgba(255,255,255,0.1)',
  borderRadius: '0.5rem', fontSize: '11px',
};

function probabilityLabel(value: number | null | undefined) {
  return value == null ? 'Unknown' : Math.round(value * 100) + '%';
}

export function FacilityDrawer({ facility, detail, isLoading, error, onRetry, onClose }: FacilityDrawerProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const isOpen = facility !== null;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!isOpen || !dialog) return;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    dialog.showModal();
    document.body.style.overflow = 'hidden';
    return () => {
      dialog.close();
      document.body.style.overflow = previousOverflow;
      if (trigger?.isConnected) trigger.focus({ preventScroll: true });
    };
  }, [isOpen]);

  // Do not paint the previous facility's response during a selection change.
  const currentDetail = detail?.facility_id === facility?.id ? detail : null;
  const explanation = currentDetail?.explanation;
  const trajectory = currentDetail?.stock_trajectory;
  const trajectoryData = trajectory?.days.map((day, index) => {
    const lower = trajectory.p10[index];
    const upper = trajectory.p90[index];
    return {
      day: 'T+' + day,
      band: lower == null || upper == null ? null : [lower, upper],
      median: trajectory.p50[index],
    };
  }) ?? [];
  const hasTrajectory = trajectoryData.some((point) => point.median != null);
  const historyData = currentDetail?.history.slice(-14).map((row) => ({
    date: row.date.slice(5), requested: row.requested_units, fulfilled: row.fulfilled_units,
  })) ?? [];

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="facility-detail-title"
      aria-busy={isLoading}
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onKeyDown={(event) => {
        if (event.key !== 'Tab') return;
        const stops = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(
          'button, a[href], input, select, textarea, summary, [tabindex]'
        )).filter((element) => element.tabIndex >= 0 && !element.hasAttribute('disabled') && element.getClientRects().length > 0);
        const first = stops[0];
        const last = stops[stops.length - 1];
        // Keep Tab navigation in the panel, including browsers that otherwise
        // move from the first/last control into browser chrome.
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right ||
            event.clientY < bounds.top || event.clientY > bounds.bottom) onClose();
      }}
      className="fixed inset-y-0 left-auto right-0 m-0 h-dvh max-h-none w-full sm:w-[520px] max-w-full border-0 border-l border-white/[0.08] bg-slate-950 text-foreground p-0 shadow-2xl open:flex open:flex-col"
    >
      {facility && <>
        <div className="px-5 py-5 border-b border-border flex items-start justify-between gap-3 bg-card/60">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 text-xs font-mono text-muted-foreground">
              <span className="text-blue-300">{facility.id}</span>
              <span>Tier: {facility.type}</span>
              <span>Depot: {facility.depot_id}</span>
            </div>
            <h2 id="facility-detail-title" className="text-xl font-bold text-white mt-2">{facility.name}</h2>
            <p className="text-xs text-muted-foreground mt-1">{facility.lat.toFixed(4)}° N · {facility.lon.toFixed(4)}° E</p>
          </div>
          <button autoFocus aria-label="Close facility details" onClick={onClose}
            className="size-10 shrink-0 rounded-xl bg-secondary flex items-center justify-center hover:bg-muted border border-border">
            <X className="size-4" />
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto p-5 space-y-5">
          {error ? (
            <div role="alert" className="rounded-xl border border-rose-500/40 bg-rose-950/30 p-4 space-y-3 text-sm">
              <p>Facility details unavailable. {error}</p>
              <button onClick={onRetry} className="rounded-lg bg-secondary px-4 py-2 font-semibold">Retry facility details</button>
            </div>
          ) : isLoading || !currentDetail || !explanation ? (
            <p role="status" className="py-20 text-center text-sm text-muted-foreground">Loading facility forecast…</p>
          ) : <>
            <section className="p-4 rounded-xl border border-border bg-card/70 space-y-3">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-xs font-bold text-muted-foreground uppercase tracking-wide">Current risk rating</h3>
                <span className={'text-xs px-3 py-1 rounded-full border font-bold ' + RISK_CLASSES[explanation.risk_state]}>
                  {explanation.risk_state}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2 border-t border-border pt-3">
                {[
                  ['Usable stock', explanation.current_usable_stock ?? 'Unknown', 'units'],
                  ['7d shortage', probabilityLabel(explanation.shortage_probability_7d), 'sampled probability'],
                  ['14d shortage', probabilityLabel(explanation.shortage_probability_14d), 'sampled probability'],
                ].map(([label, value, unit]) => (
                  <div key={label} className="p-2 rounded-lg bg-secondary/50 text-center">
                    <p className="text-[10px] text-muted-foreground uppercase">{label}</p>
                    <p className="text-base sm:text-lg font-bold text-white mt-1">{value}</p>
                    <p className="text-[9px] text-muted-foreground">{unit}</p>
                  </div>
                ))}
              </div>
              {explanation.risk_state === 'Unknown' && <p className="text-xs text-amber-300">Missing or stale evidence prevents a reliable estimate. This facility is excluded from regional totals and transfer planning.</p>}
            </section>

            <section className="p-4 rounded-xl border border-border bg-card/70 space-y-3">
              <h3 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide"><TrendingUp className="size-4 text-primary" />Stock forecast · P10–P90 range</h3>
              {hasTrajectory ? <>
                <div className="h-48 w-full" role="img" aria-label="Daily stock forecast with a median line and P10 to P90 uncertainty band">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={trajectoryData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }} accessibilityLayer>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                      <XAxis dataKey="day" stroke="#64748b" fontSize={10} tickLine={false} />
                      <YAxis stroke="#64748b" fontSize={10} tickLine={false} />
                      <RechartsTooltip contentStyle={TOOLTIP_STYLE} />
                      <Area type="linear" dataKey="band" stroke="#60a5fa" fill="#3b82f6" fillOpacity={0.2} name="P10–P90 range" isAnimationActive={false} />
                      <Line type="linear" dataKey="median" stroke="#10b981" strokeWidth={2} dot={false} name="Median (P50)" isAnimationActive={false} />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
                <p className="text-[11px] text-muted-foreground">Green: median stock. Blue: P10–P90 range across {currentDetail.path_count} sampled paths. These are model estimates, not best or worst possible outcomes.</p>
              </> : <p className="text-xs text-muted-foreground">Stock forecast unavailable because evidence is incomplete.</p>}
            </section>

            <section className="p-4 rounded-xl border border-border bg-card/70 space-y-3">
              <h3 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide"><Calendar className="size-4 text-blue-400" />Recent requested and fulfilled demand</h3>
              {historyData.length > 0 ? <div className="h-36 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={historyData} margin={{ top: 5, right: 10, left: -25, bottom: 0 }} accessibilityLayer>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                    <XAxis dataKey="date" stroke="#64748b" fontSize={9} tickLine={false} />
                    <YAxis stroke="#64748b" fontSize={9} tickLine={false} />
                    <RechartsTooltip contentStyle={TOOLTIP_STYLE} />
                    <Bar dataKey="requested" fill="#f59e0b" name="Requested units" isAnimationActive={false} />
                    <Bar dataKey="fulfilled" fill="#3b82f6" name="Fulfilled units" isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </div> : <p className="text-xs text-muted-foreground">No recent demand records.</p>}
              <p className="text-[11px] text-muted-foreground">Amber: requested. Blue: fulfilled. Missing requests are left blank.</p>
            </section>

            <section className="p-4 rounded-xl border border-border bg-card/70 space-y-3">
              <h3 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide"><AlertCircle className="size-4 text-amber-400" />Supporting evidence</h3>
              {explanation.primary_factors.length > 0 ? explanation.primary_factors.map((factor) => (
                <div key={factor.code} className="p-3 rounded-lg border border-border bg-secondary/40 text-xs space-y-1.5">
                  <p className="font-bold text-white">{factor.title}</p>
                  <p className="text-muted-foreground leading-relaxed">{factor.description}</p>
                </div>
              )) : <p className="text-xs text-muted-foreground">No additional rule-based factors identified in the available records.</p>}
            </section>

            {currentDetail.pending_shipments.length > 0 && <section className="p-4 rounded-xl border border-border bg-card/70 space-y-3">
              <h3 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide"><Truck className="size-4 text-emerald-400" />Pending inbound shipments</h3>
              {currentDetail.pending_shipments.map((shipment) => (
                <div key={shipment.id} className="p-3 rounded-lg bg-secondary/40 border border-border text-xs space-y-2">
                  <p className="font-bold text-white">{shipment.quantity_units} units <span className="font-normal text-muted-foreground">from {shipment.depot_id}</span></p>
                  <p className="flex items-start gap-1.5 text-muted-foreground"><Clock className="size-3 shrink-0 mt-0.5" />
                    <span>{shipment.route_blocked ? 'Route closed: no modeled arrival.' : shipment.projected_arrival_day == null ? 'No modeled arrival within the forecast horizon.' : 'Median scenario arrival: T+' + shipment.projected_arrival_day + '.'} Promised: T+{shipment.promised_arrival_day}.</span>
                  </p>
                  <p className="text-[10px] text-muted-foreground">Source status: {shipment.status} · Expires: {shipment.expires_on}</p>
                </div>
              ))}
            </section>}

            <details className="text-xs text-muted-foreground rounded-xl border border-border p-3">
              <summary className="cursor-pointer font-semibold">Forecast assumptions · revision #{currentDetail.revision}</summary>
              <ul className="mt-2 list-disc pl-4 space-y-1">{currentDetail.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul>
            </details>
          </>}
        </div>
      </>}
    </dialog>
  );
}
