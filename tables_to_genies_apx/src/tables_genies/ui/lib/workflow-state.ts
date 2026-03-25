/**
 * Workflow state management utility for persisting page state across refreshes.
 */

const STORAGE_PREFIX = 'workflow.';
const STATE_VERSION = '1.0';
const EXPIRATION_MS = 24 * 60 * 60 * 1000; // 24 hours
const STEPS_KEY = 'workflow.completed-steps';

export type WorkflowStep =
  | 'tables-selected'
  | 'enrichment-done'
  | 'graph-built'
  | 'rooms-defined'
  | 'rooms-created';

function getCompletedSteps(): Set<WorkflowStep> {
  try {
    const item = localStorage.getItem(STEPS_KEY);
    if (!item) return new Set();
    return new Set(JSON.parse(item));
  } catch {
    return new Set();
  }
}

export function markStepCompleted(step: WorkflowStep): void {
  try {
    const steps = getCompletedSteps();
    steps.add(step);
    localStorage.setItem(STEPS_KEY, JSON.stringify([...steps]));
  } catch (e) {
    console.error('Failed to mark step completed:', e);
  }
}

export function isStepCompleted(step: WorkflowStep): boolean {
  return getCompletedSteps().has(step);
}

export interface CatalogBrowserState {
  selectedTables: string[];
  selectedCatalog: string | null;
  selectedSchema: string | null;
  allCatalogTables: Record<string, any[]>;
}

export interface EnrichmentState {
  jobId: number | null;
  jobUrl: string | null;
  metadataTable: string;
  chunksTable: string;
  writeMode: 'overwrite' | 'append' | 'error';
}

export interface GraphExplorerState {
  graphBuilt: boolean;
  showStructuralEdges: boolean;
  showSemanticEdges: boolean;
  highlightedCommunity: string | null;
  expandedRoomName: string | null;
}

export interface GenieBuilderState {
  roomName: string;
  selectedTableFqns: string[];
}

export interface GenieCreateState {
  creationStarted: boolean;
}

export type WorkflowStateMap = {
  'catalog-browser': CatalogBrowserState;
  'enrichment': EnrichmentState;
  'graph-explorer': GraphExplorerState;
  'genie-builder': GenieBuilderState;
  'genie-create': GenieCreateState;
};

interface StoredState<T> {
  version: string;
  timestamp: number;
  data: T;
}

/**
 * Saves state for a specific page to localStorage.
 */
export function saveState<K extends keyof WorkflowStateMap>(
  pageKey: K,
  data: WorkflowStateMap[K]
): void {
  try {
    const stored: StoredState<WorkflowStateMap[K]> = {
      version: STATE_VERSION,
      timestamp: Date.now(),
      data,
    };
    localStorage.setItem(STORAGE_PREFIX + pageKey, JSON.stringify(stored));
  } catch (error) {
    console.error(`Failed to save state for ${pageKey}:`, error);
  }
}

/**
 * Loads state for a specific page from localStorage.
 * Returns null if no state exists, version mismatch, or state expired.
 */
export function loadState<K extends keyof WorkflowStateMap>(
  pageKey: K
): WorkflowStateMap[K] | null {
  try {
    const item = localStorage.getItem(STORAGE_PREFIX + pageKey);
    if (!item) return null;

    const stored: StoredState<WorkflowStateMap[K]> = JSON.parse(item);

    // Check version
    if (stored.version !== STATE_VERSION) {
      console.warn(`State version mismatch for ${pageKey}. Clearing state.`);
      localStorage.removeItem(STORAGE_PREFIX + pageKey);
      return null;
    }

    // Check expiration
    if (Date.now() - stored.timestamp > EXPIRATION_MS) {
      console.warn(`State expired for ${pageKey}. Clearing state.`);
      localStorage.removeItem(STORAGE_PREFIX + pageKey);
      return null;
    }

    return stored.data;
  } catch (error) {
    console.error(`Failed to load state for ${pageKey}:`, error);
    return null;
  }
}

/**
 * Clears all workflow-related state from localStorage.
 */
export function clearAllWorkflowState(): void {
  try {
    const keysToRemove: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith(STORAGE_PREFIX)) {
        keysToRemove.push(key);
      }
    }
    keysToRemove.forEach((key) => localStorage.removeItem(key));
    // Also clear the graph-explorer-built key if it exists separately
    localStorage.removeItem('graph-explorer-built');
    localStorage.removeItem('graph-explorer-state');
    // Clear workflow step tracking
    localStorage.removeItem(STEPS_KEY);
    // Clear any other potential keys that might be used
    localStorage.removeItem('selected-tables');
    localStorage.removeItem('catalog-browser-state');
    localStorage.removeItem('enrichment-state');
    localStorage.removeItem('genie-builder-state');
    localStorage.removeItem('genie-create-state');
  } catch (error) {
    console.error('Failed to clear workflow state:', error);
  }
}
