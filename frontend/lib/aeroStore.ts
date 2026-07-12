'use client';
import { create } from 'zustand';
import type { Strategy, StrategyDetail, PipelineRun, StageStatus, AeRoing4RunState, WorkflowStep, BackendSettings } from './api';

export type MainTab = 'read' | 'learn' | 'fix' | 'test' | 'autoquant' | 'settings';

interface AeroState {
  // Navigation
  activeTab: MainTab;
  setActiveTab: (tab: MainTab) => void;

  // Theme
  darkMode: boolean;
  toggleDarkMode: () => void;

  // Backend connection / settings
  apiBaseUrl: string;
  setApiBaseUrl: (url: string) => void;
  backendConnected: boolean;
  setBackendConnected: (v: boolean) => void;
  backendStatus: string;
  setBackendStatus: (v: string) => void;
  backendSettings: BackendSettings | null;
  setBackendSettings: (s: BackendSettings | null) => void;
  backendSettingsLoading: boolean;
  setBackendSettingsLoading: (v: boolean) => void;
  backendSettingsDirty: boolean;
  setBackendSettingsDirty: (v: boolean) => void;

  // Local UI overrides (kept for convenience, synced with backend settings when loaded)
  defaultStrategyPath: string;
  setDefaultStrategyPath: (path: string) => void;
  hyperoptEpochs: number;
  setHyperoptEpochs: (n: number) => void;
  defaultTimerange: string;
  setDefaultTimerange: (t: string) => void;

  // Strategies
  strategies: Strategy[];
  setStrategies: (s: Strategy[]) => void;
  selectedStrategy: StrategyDetail | null;
  setSelectedStrategy: (s: StrategyDetail | null) => void;
  selectedStrategyName: string;
  setSelectedStrategyName: (name: string) => void;

  // AeRoing4 Milestone 2A
  aering4Run: AeRoing4RunState | null;
  setAering4Run: (run: AeRoing4RunState | null) => void;
  updateAering4Step: (stepId: string, patch: Partial<WorkflowStep>) => void;
  appendAering4Log: (stepId: string, line: string) => void;
  aering4Running: boolean;
  setAering4Running: (v: boolean) => void;
  discoveryPairs: string[];
  setDiscoveryPairs: (pairs: string[]) => void;
  discoveryTimerange: string;
  setDiscoveryTimerange: (t: string) => void;
  aering4StrategyName: string;
  setAering4StrategyName: (n: string) => void;

  // AutoQuant pipeline
  pipelineRun: PipelineRun | null;
  setPipelineRun: (run: PipelineRun | null) => void;
  updateStage: (stageId: number, patch: Partial<StageStatus>) => void;
  appendLog: (stageId: number, line: string) => void;
  pipelineRunning: boolean;
  setPipelineRunning: (v: boolean) => void;
  selectedPairs: string[];
  setSelectedPairs: (pairs: string[]) => void;
}

export const useAeroStore = create<AeroState>((set) => ({
  activeTab: 'read',
  setActiveTab: (tab) => set({ activeTab: tab }),

  darkMode: true,
  toggleDarkMode: () => set((s) => ({ darkMode: !s.darkMode })),

  apiBaseUrl: 'http://127.0.0.1:8000',
  setApiBaseUrl: (url) => set({ apiBaseUrl: url }),
  backendConnected: false,
  setBackendConnected: (v) => set({ backendConnected: v }),
  backendStatus: 'CHECKING',
  setBackendStatus: (v) => set({ backendStatus: v }),
  backendSettings: null,
  setBackendSettings: (s) => set({ backendSettings: s }),
  backendSettingsLoading: false,
  setBackendSettingsLoading: (v) => set({ backendSettingsLoading: v }),
  backendSettingsDirty: false,
  setBackendSettingsDirty: (v) => set({ backendSettingsDirty: v }),

  defaultStrategyPath: '/freqtrade/user_data/strategies',
  setDefaultStrategyPath: (path) => set({ defaultStrategyPath: path }),
  hyperoptEpochs: 100,
  setHyperoptEpochs: (n) => set({ hyperoptEpochs: n }),
  defaultTimerange: '20230101-20240101',
  setDefaultTimerange: (t) => set({ defaultTimerange: t }),

  strategies: [],
  setStrategies: (strategies) => set({ strategies }),
  selectedStrategy: null,
  setSelectedStrategy: (selectedStrategy) => set({ selectedStrategy }),
  selectedStrategyName: '',
  setSelectedStrategyName: (selectedStrategyName) => set({ selectedStrategyName }),

  aering4Run: null,
  setAering4Run: (aering4Run) => set({ aering4Run }),
  updateAering4Step: (stepId, patch) =>
    set((s) => {
      if (!s.aering4Run) return s;
      return { aering4Run: { ...s.aering4Run, steps: s.aering4Run.steps.map(st => st.id === stepId ? { ...st, ...patch } : st) } };
    }),
  appendAering4Log: (stepId, line) =>
    set((s) => {
      if (!s.aering4Run) return s;
      return { aering4Run: { ...s.aering4Run, steps: s.aering4Run.steps.map(st => st.id === stepId ? { ...st, logs: [...st.logs, line] } : st) } };
    }),
  aering4Running: false,
  setAering4Running: (aering4Running) => set({ aering4Running }),
  discoveryPairs: [],
  setDiscoveryPairs: (discoveryPairs) => set({ discoveryPairs }),
  discoveryTimerange: '20230101-20231231',
  setDiscoveryTimerange: (discoveryTimerange) => set({ discoveryTimerange }),
  aering4StrategyName: '',
  setAering4StrategyName: (aering4StrategyName) => set({ aering4StrategyName }),

  pipelineRun: null,
  setPipelineRun: (pipelineRun) => set({ pipelineRun }),
  updateStage: (stageId, patch) =>
    set((s) => {
      if (!s.pipelineRun) return s;
      return {
        pipelineRun: {
          ...s.pipelineRun,
          stages: s.pipelineRun.stages.map((st) =>
            st.id === stageId ? { ...st, ...patch } : st
          ),
        },
      };
    }),
  appendLog: (stageId, line) =>
    set((s) => {
      if (!s.pipelineRun) return s;
      return {
        pipelineRun: {
          ...s.pipelineRun,
          stages: s.pipelineRun.stages.map((st) =>
            st.id === stageId ? { ...st, logs: [...st.logs, line] } : st
          ),
        },
      };
    }),
  pipelineRunning: false,
  setPipelineRunning: (pipelineRunning) => set({ pipelineRunning }),
  selectedPairs: ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
  setSelectedPairs: (selectedPairs) => set({ selectedPairs }),
}));
