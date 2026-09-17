import React, { useEffect, useState } from 'react';
import { MapContainer, TileLayer, CircleMarker, Marker, Popup, Polyline, Tooltip, useMap } from 'react-leaflet';
import L from 'leaflet';
import { Play, Pause, RotateCcw, Truck } from 'lucide-react';
import { Facility, Depot, Route, FacilityRiskSummary, Transfer } from '../lib/types';

const RISK_COLORS: Record<FacilityRiskSummary['risk_state'], string> = {
  'High risk': '#ef4444', Watch: '#eab308', 'Lower risk': '#22c55e',
  Empty: '#71717a', Unknown: '#94a3b8',
};

interface FacilityMapProps {
  facilities: Facility[];
  depots: Depot[];
  routes: Route[];
  closedRouteIds: string[];
  facilityRisks: Record<string, FacilityRiskSummary>;
  selectedFacilityId: string | null;
  onSelectFacility: (facilityId: string) => void;
  activeTransfers: Transfer[];
  showTransfers: boolean;
  onToggleTransfers: (show: boolean) => void;
  currentDay: number;
  onDayChange: (day: number) => void;
}

function MapAutoFit({ facilities, depots }: { facilities: Facility[]; depots: Depot[] }) {
  const map = useMap();
  useEffect(() => {
    const locations = [...facilities, ...depots];
    if (locations.length) map.fitBounds(L.latLngBounds(locations.map((item) => [item.lat, item.lon])), { padding: [35, 35] });
  }, [facilities, depots, map]);
  return null;
}

function depotIcon() {
  return L.divIcon({
    className: 'custom-depot-marker',
    html: '<div class="size-8 rounded-lg bg-blue-600 border-2 border-white text-white text-center font-bold leading-7">D</div>',
    iconSize: [32, 32], iconAnchor: [16, 16],
  });
}

export const FacilityMap: React.FC<FacilityMapProps> = ({
  facilities, depots, routes, closedRouteIds, facilityRisks, selectedFacilityId,
  onSelectFacility, activeTransfers, showTransfers, onToggleTransfers, currentDay, onDayChange,
}) => {
  const [isPlaying, setIsPlaying] = useState(false);
  useEffect(() => {
    if (!isPlaying) return;
    const timer = setInterval(() => onDayChange((currentDay + 1) % 14), 1300);
    return () => clearInterval(timer);
  }, [isPlaying, currentDay, onDayChange]);

  const riskState = (facilityId: string): FacilityRiskSummary['risk_state'] => {
    const risk = facilityRisks[facilityId];
    if (!risk || risk.flags.length) return 'Unknown';
    return risk.daily_risk_state[currentDay] ?? 'Unknown';
  };

  return (
    <div className="w-full min-w-0 rounded-2xl overflow-hidden border border-border/80 bg-card shadow-xl">
      <div className="p-4 flex flex-wrap items-center gap-3 border-b border-border">
        <div className="min-w-0 flex-1 basis-full sm:basis-auto">
          <h2 className="text-sm font-bold">District inventory forecast</h2>
          <p className="text-xs text-muted-foreground">Without transfers · modeled end of day {currentDay}</p>
        </div>
        <label className="text-xs text-muted-foreground min-w-0">
          Inspect facility
          <select aria-label="Inspect facility" value={selectedFacilityId || ''}
            onChange={(event) => event.target.value && onSelectFacility(event.target.value)}
            className="block mt-1 max-w-full w-60 rounded-lg border border-border bg-secondary px-2 py-1 text-foreground">
            <option value="">Select a facility…</option>
            {facilities.map((facility) => <option key={facility.id} value={facility.id}>{facility.name} · {riskState(facility.id)}</option>)}
          </select>
        </label>
        <button onClick={() => onToggleTransfers(!showTransfers)} aria-pressed={showTransfers}
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-xs text-emerald-300">
          <Truck className="size-4" /> Proposed routes ({activeTransfers.length})
        </button>
        <div className="w-full flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {Object.entries(RISK_COLORS).map(([state, color]) => (
            <span key={state} className="inline-flex items-center gap-1.5">
              <span className="size-2 rounded-full" style={{ backgroundColor: color }} />{state}
            </span>
          ))}
        </div>
      </div>

      <div className="h-[380px] sm:h-[440px] w-full">
        <MapContainer center={[13.34, 74.78]} zoom={10} scrollWheelZoom className="w-full h-full z-0">
          <MapAutoFit facilities={facilities} depots={depots} />
          <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />

          {routes.filter((route) => route.kind === 'SUPPLY').map((route) => {
            const depot = depots.find((item) => item.id === route.from_id);
            const facility = facilities.find((item) => item.id === route.to_id);
            if (!depot || !facility) return null;
            const blocked = !route.enabled || closedRouteIds.includes(route.id);
            return <Polyline key={route.id} positions={[[depot.lat, depot.lon], [facility.lat, facility.lon]]}
              pathOptions={{ color: blocked ? '#ef4444' : '#3b82f6', weight: blocked ? 2 : 1.5, dashArray: '4, 8', opacity: 0.5 }}>
              <Tooltip>{route.id} · {blocked ? 'Closed in scenario' : 'Configured supplier route'}</Tooltip>
            </Polyline>;
          })}

          {depots.map((depot) => <Marker key={depot.id} position={[depot.lat, depot.lon]} icon={depotIcon()}>
            <Popup><strong>{depot.name}</strong><p>Simulated supplier depot · {depot.id}</p></Popup>
          </Marker>)}

          {showTransfers && activeTransfers.map((transfer) => {
            const donor = facilities.find((item) => item.id === transfer.from_facility_id);
            const recipient = facilities.find((item) => item.id === transfer.to_facility_id);
            if (!donor || !recipient) return null;
            const arrived = currentDay >= transfer.arrival_day;
            return <Polyline key={transfer.id} positions={[[donor.lat, donor.lon], [recipient.lat, recipient.lon]]}
              pathOptions={{ className: arrived ? '' : 'leaflet-transfer-arc', color: '#22c55e', weight: 3,
                dashArray: arrived ? undefined : '8, 8', opacity: arrived ? 0.45 : 0.9 }}>
              <Tooltip>{transfer.quantity_units} units · {arrived ? 'would have arrived' : 'would be in transit'} · arrival day {transfer.arrival_day}</Tooltip>
            </Polyline>;
          })}

          {facilities.map((facility) => {
            const state = riskState(facility.id);
            const color = RISK_COLORS[state];
            const risk = facilityRisks[facility.id];
            const probability = risk?.daily_shortage_probability[currentDay];
            return <CircleMarker key={facility.id} center={[facility.lat, facility.lon]}
              radius={facility.id === selectedFacilityId ? 12 : 9}
              pathOptions={{ fillColor: color, fillOpacity: 0.95, color: facility.id === selectedFacilityId ? '#fff' : color, weight: 2 }}
              eventHandlers={{ click: () => onSelectFacility(facility.id) }}>
              <Tooltip direction="top" offset={[0, -8]}>
                <div className="p-1 text-xs text-slate-900">
                  <strong>{facility.name}</strong>
                  <p>End of day {currentDay}: {state}</p>
                  <p>Daily unmet-demand probability: {probability == null ? 'Unknown' : Math.round(probability * 100) + '%'}</p>
                  <p>Median closing stock: {risk?.daily_stock_p50[currentDay] ?? 'Unknown'} units</p>
                  <p>Current observed stock: {risk?.current_usable_stock ?? 'Unknown'} units</p>
                </div>
              </Tooltip>
            </CircleMarker>;
          })}
        </MapContainer>
      </div>

      <div className="p-4 flex flex-wrap items-center gap-3 border-t border-border bg-card">
        <button onClick={() => setIsPlaying((playing) => !playing)}
          aria-label={isPlaying ? 'Pause time-lapse' : 'Play time-lapse'}
          className="size-9 rounded-lg bg-primary text-primary-foreground flex items-center justify-center">
          {isPlaying ? <Pause className="size-4" /> : <Play className="size-4" />}
        </button>
        <button onClick={() => { setIsPlaying(false); onDayChange(0); }} aria-label="Reset to day 0"
          className="size-9 rounded-lg border border-border flex items-center justify-center">
          <RotateCcw className="size-4" />
        </button>
        <label className="flex-1 min-w-32 text-xs text-muted-foreground">
          End of day {currentDay} / 13
          <input aria-label="Forecast day" type="range" min={0} max={13} value={currentDay}
            onChange={(event) => onDayChange(Number(event.target.value))}
            className="block mt-2 w-full accent-primary" />
        </label>
        <p className="w-full text-[11px] text-muted-foreground">The optional online basemap may be unavailable offline; facility markers and configured routes remain usable.</p>
      </div>
    </div>
  );
};
