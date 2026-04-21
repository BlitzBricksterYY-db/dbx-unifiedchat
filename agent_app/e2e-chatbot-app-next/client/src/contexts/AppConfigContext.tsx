import { createContext, useContext, type ReactNode } from 'react';
import useSWR from 'swr';
import { fetcher } from '@/lib/utils';

export interface GenieSpaceResource {
  id: string;
  name: string;
  url: string;
}

export interface MlflowExperimentResource {
  id: string;
  url: string;
}

interface ConfigResponse {
  features: {
    chatHistory: boolean;
    feedback: boolean;
  };
  resources?: {
    appLogoUrl: string | null;
    genieSpaces: GenieSpaceResource[];
    mlflowExperiment: MlflowExperimentResource | null;
  };
}

interface AppConfigContextType {
  config: ConfigResponse | undefined;
  isLoading: boolean;
  error: Error | undefined;
  chatHistoryEnabled: boolean;
  feedbackEnabled: boolean;
  genieSpaces: GenieSpaceResource[];
  mlflowExperiment: MlflowExperimentResource | null;
  appLogoUrl: string | null;
}

const AppConfigContext = createContext<AppConfigContextType | undefined>(
  undefined,
);

export function AppConfigProvider({ children }: { children: ReactNode }) {
  const { data, error, isLoading } = useSWR<ConfigResponse>(
    '/api/config',
    fetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      dedupingInterval: 60000,
    },
  );

  const value: AppConfigContextType = {
    config: data,
    isLoading,
    error,
    chatHistoryEnabled: data?.features.chatHistory ?? true,
    feedbackEnabled: data?.features.feedback ?? false,
    appLogoUrl: data?.resources?.appLogoUrl ?? null,
    genieSpaces: data?.resources?.genieSpaces ?? [],
    mlflowExperiment: data?.resources?.mlflowExperiment ?? null,
  };

  return (
    <AppConfigContext.Provider value={value}>
      {children}
    </AppConfigContext.Provider>
  );
}

export function useAppConfig() {
  const context = useContext(AppConfigContext);
  if (context === undefined) {
    throw new Error('useAppConfig must be used within an AppConfigProvider');
  }
  return context;
}
