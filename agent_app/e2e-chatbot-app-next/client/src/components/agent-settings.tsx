'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

export type ExecutionMode = 'parallel' | 'sequential';
export type SynthesisRoute = 'auto' | 'table_route' | 'genie_route';

export interface AgentSettings {
  executionMode: ExecutionMode;
  synthesisRoute: SynthesisRoute;
}

function loadSettings(initialSettings?: Partial<AgentSettings>): AgentSettings {
  return {
    executionMode: initialSettings?.executionMode ?? 'parallel',
    synthesisRoute: initialSettings?.synthesisRoute ?? 'auto',
  };
}

export function useAgentSettings(initialSettings?: Partial<AgentSettings>) {
  const [settings, setSettings] = useState<AgentSettings>(() =>
    loadSettings(initialSettings),
  );
  const settingsRef = useRef(settings);

  useEffect(() => {
    settingsRef.current = settings;
  }, [settings]);

  const update = useCallback((patch: Partial<AgentSettings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch };
      settingsRef.current = next;
      return next;
    });
  }, []);

  return { settings, settingsRef, update };
}

const routeLabels: Record<SynthesisRoute, string> = {
  auto: 'Auto',
  table_route: 'Table',
  genie_route: 'Genie',
};

export function AgentSettingsPanel({
  settings,
  onUpdate,
}: {
  settings: AgentSettings;
  onUpdate: (patch: Partial<AgentSettings>) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draftSettings, setDraftSettings] = useState(settings);

  useEffect(() => {
    if (!open) {
      setDraftSettings(settings);
    }
  }, [open, settings]);

  const handleOpenChange = useCallback(() => {
    setOpen((prev) => {
      const next = !prev;
      if (next) {
        setDraftSettings(settings);
      }
      return next;
    });
  }, [settings]);

  const handleCancel = useCallback(() => {
    setDraftSettings(settings);
    setOpen(false);
  }, [settings]);

  const handleConfirm = useCallback(() => {
    onUpdate(draftSettings);
    setOpen(false);
  }, [draftSettings, onUpdate]);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={handleOpenChange}
        className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-zinc-500 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
        title="Agent settings"
        data-testid="agent-settings-trigger"
        aria-expanded={open}
        aria-controls="agent-settings-panel"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
          <circle cx="12" cy="12" r="3" />
        </svg>
        Settings
      </button>

      {open && (
        <div
          id="agent-settings-panel"
          data-testid="agent-settings-panel"
          className="absolute bottom-full left-0 z-50 mb-2 w-64 rounded-lg border border-zinc-200 bg-white p-3 shadow-lg dark:border-zinc-700 dark:bg-zinc-900"
        >
          <div className="mb-3 text-xs font-semibold text-zinc-700 dark:text-zinc-300">
            Agent Settings
          </div>

          {/* Execution mode toggle */}
          <div className="mb-3">
            <label className="mb-1 block text-xs text-zinc-500 dark:text-zinc-400">
              Execution Mode
            </label>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() =>
                  setDraftSettings((prev) => ({
                    ...prev,
                    executionMode:
                      prev.executionMode === 'parallel'
                        ? 'sequential'
                        : 'parallel',
                  }))
                }
                role="switch"
                aria-label="Execution mode"
                aria-checked={draftSettings.executionMode === 'sequential'}
                data-testid="execution-mode-toggle"
                className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
                  draftSettings.executionMode === 'sequential'
                    ? 'bg-blue-600'
                    : 'bg-zinc-200 dark:bg-zinc-700'
                }`}
              >
                <span
                  className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${
                    draftSettings.executionMode === 'sequential'
                      ? 'translate-x-4'
                      : 'translate-x-0'
                  }`}
                />
              </button>
              <span
                data-testid="execution-mode-value"
                className="text-xs text-zinc-600 dark:text-zinc-300"
              >
                {draftSettings.executionMode === 'sequential'
                  ? 'Sequential'
                  : 'Parallel'}
              </span>
            </div>
            <p className="mt-0.5 text-[10px] text-zinc-400">
              Sequential feeds each result into the next query
            </p>
          </div>

          {/* Synthesis route selector */}
          <div>
            <label className="mb-1 block text-xs text-zinc-500 dark:text-zinc-400">
              Synthesis Route
            </label>
            <div className="flex rounded-md border border-zinc-200 dark:border-zinc-700">
              {(
                ['auto', 'table_route', 'genie_route'] as SynthesisRoute[]
              ).map((route) => (
                <button
                  key={route}
                  type="button"
                  onClick={() =>
                    setDraftSettings((prev) => ({
                      ...prev,
                      synthesisRoute: route,
                    }))
                  }
                  data-testid={`synthesis-route-${route}`}
                  aria-pressed={draftSettings.synthesisRoute === route}
                  className={`flex-1 px-2 py-1 text-xs font-medium transition-colors first:rounded-l-md last:rounded-r-md ${
                    draftSettings.synthesisRoute === route
                      ? 'bg-blue-600 text-white'
                      : 'text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800'
                  }`}
                >
                  {routeLabels[route]}
                </button>
              ))}
            </div>
            <p className="mt-0.5 text-[10px] text-zinc-400">
              Auto lets the planner decide; Table uses UC functions; Genie uses
              Genie agents
            </p>
          </div>

          <div className="mt-3 flex justify-end gap-2">
            <button
              type="button"
              onClick={handleCancel}
              data-testid="agent-settings-cancel"
              className="rounded-md border border-zinc-200 px-2 py-1 text-xs font-medium text-zinc-600 transition-colors hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleConfirm}
              data-testid="agent-settings-confirm"
              className="rounded-md bg-blue-600 px-2 py-1 text-xs font-medium text-white transition-colors hover:bg-blue-700"
            >
              Confirm
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
