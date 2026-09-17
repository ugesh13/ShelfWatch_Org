import React from 'react';
import { motion } from 'framer-motion';
import { Activity, ShieldAlert, RefreshCw, Layers, Database, ChevronDown } from 'lucide-react';
import { FixtureMeta, Product } from '../lib/types';

interface HeaderProps {
  fixtures: FixtureMeta[];
  selectedFixtureId: string;
  onSelectFixture: (fixtureId: string) => void;
  products: Product[];
  selectedSkuId: string;
  onSelectSku: (skuId: string) => void;
  isRunning: boolean;
  selectorsDisabled: boolean;
  isConnected: boolean;
  onRunSimulation: () => void;
  revision: number;
}

export const Header: React.FC<HeaderProps> = ({
  fixtures,
  selectedFixtureId,
  onSelectFixture,
  products,
  selectedSkuId,
  onSelectSku,
  isRunning,
  selectorsDisabled,
  isConnected,
  onRunSimulation,
  revision,
}) => {
  return (
    <header className="border-b border-border/80 bg-card/60 backdrop-blur-xl px-4 sm:px-6 py-3.5 flex flex-wrap items-center justify-between gap-4 lg:sticky lg:top-0 z-40 shadow-sm shadow-black/20">
      {/* Brand & System Status */}
      <div className="flex items-center gap-4 min-w-0 max-w-full">
        <div className="flex items-center gap-3">
          <div className="relative flex items-center justify-center">
            <span className="absolute -top-0.5 -right-0.5 flex size-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full size-2.5 bg-emerald-500"></span>
            </span>
            <div className="size-10 rounded-xl bg-gradient-to-br from-blue-600/30 to-indigo-600/20 border border-blue-500/40 flex items-center justify-center text-blue-400 shadow-inner">
              <Activity className="size-5 text-blue-400" />
            </div>
          </div>

          <div>
            <div className="flex flex-wrap items-center gap-2.5">
              <span className="text-xl font-extrabold tracking-tight text-white bg-clip-text text-transparent bg-gradient-to-r from-white via-slate-100 to-slate-400">
                ShelfWatch
              </span>
              <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 font-semibold tracking-wide flex items-center gap-1">
                <span className="size-1.5 rounded-full bg-emerald-400 animate-pulse" />
                {isConnected ? 'SIMULATED SCENARIO' : 'CONNECTING TO ENGINE'}
              </span>
            </div>
            <p className="text-xs text-muted-foreground font-medium">
              Medicine shortage forecasts &bull; Redistribution planning
            </p>
          </div>
        </div>

        {/* Demo Warning Badge */}
        <div className="hidden xl:flex items-center gap-2 text-xs bg-amber-500/10 border border-amber-500/20 text-amber-300/90 px-3 py-1.5 rounded-lg">
          <ShieldAlert className="size-4 text-amber-400 shrink-0" />
          <span className="font-medium text-[11px]">Simulated decision support &bull; Outcomes are model estimates</span>
        </div>
      </div>

      {/* Controls & Telemetry Selectors */}
      <div className="flex items-center gap-3 flex-wrap min-w-0 max-w-full">
        {/* Medicine SKU Selector */}
        <div className="relative flex items-center max-w-full bg-secondary/60 hover:bg-secondary/80 border border-border/80 rounded-xl px-3.5 py-1.5 transition-all shadow-inner group">
          <Layers className="size-4 text-primary mr-2.5 shrink-0" />
          <div className="flex flex-col pr-5 min-w-0">
            <span className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">
              Essential Medicine SKU
            </span>
            <select
              value={selectedSkuId}
              aria-label="Essential Medicine SKU"
              disabled={selectorsDisabled}
              onChange={(e) => onSelectSku(e.target.value)}
              className="bg-transparent text-sm font-semibold text-foreground cursor-pointer appearance-none max-w-full truncate"
            >
              {products.length > 0 ? (
                products.map((p) => (
                  <option key={p.sku_id} value={p.sku_id} className="bg-slate-900 text-foreground py-1">
                    {p.generic_name} {p.strength} ({p.base_unit})
                  </option>
                ))
              ) : (
                <option value="AMX500_CAP" className="bg-slate-900 text-foreground">
                  Amoxicillin 500mg (capsule)
                </option>
              )}
            </select>
          </div>
          <ChevronDown className="size-3.5 text-muted-foreground absolute right-3 pointer-events-none group-hover:text-foreground transition-colors" />
        </div>

        {/* Scenario Fixture Selector */}
        <div className="relative flex items-center bg-secondary/60 hover:bg-secondary/80 border border-border/80 rounded-xl px-3.5 py-1.5 transition-all shadow-inner group">
          <Database className="size-4 text-blue-400 mr-2.5 shrink-0" />
          <div className="flex flex-col pr-5">
            <span className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">
              Scenario Preset
            </span>
            <select
              value={selectedFixtureId}
              aria-label="Scenario Preset"
              disabled={selectorsDisabled}
              onChange={(e) => onSelectFixture(e.target.value)}
              className="bg-transparent text-sm font-semibold text-foreground cursor-pointer appearance-none max-w-[210px] truncate"
            >
              {fixtures.map((f) => (
                <option key={f.id} value={f.id} className="bg-slate-900 text-foreground py-1">
                  {f.name} {f.mode === 'deterministic' ? '· [Verified Proof]' : ''}
                </option>
              ))}
            </select>
          </div>
          <ChevronDown className="size-3.5 text-muted-foreground absolute right-3 pointer-events-none group-hover:text-foreground transition-colors" />
        </div>

        {/* Revision Tag */}
        <div className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-card border border-border/80 text-xs font-mono font-bold text-muted-foreground shadow-sm">
          <span className="text-[10px] text-primary uppercase font-sans font-extrabold tracking-wider">Rev</span>
          <span className="text-white">#{revision}</span>
        </div>

        {/* Run / Recalculate Button */}
        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          onClick={onRunSimulation}
          disabled={isRunning || !isConnected}
          className="flex items-center gap-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-bold text-sm px-4 py-2.5 rounded-xl transition-all shadow-lg shadow-blue-500/25 disabled:opacity-50 cursor-pointer border border-blue-400/30"
        >
          <RefreshCw className={`size-4 ${isRunning ? 'animate-spin' : ''}`} />
          <span>{isRunning ? 'Simulating...' : 'Run Simulation'}</span>
        </motion.button>
      </div>
    </header>
  );
};
