import {
  Router,
  type Request,
  type Response,
  type Router as RouterType,
} from 'express';
import { isDatabaseAvailable } from '@chat-template/db';
import { getWorkspaceHostname } from '@chat-template/ai-sdk-providers';
import { getDatabricksToken } from '@chat-template/auth';

export const configRouter: RouterType = Router();

let cachedResources: {
  workspaceHost: string | null;
  genieSpaces: Array<{ id: string; name: string; url: string }>;
  mlflowExperiment: { id: string; url: string } | null;
} | null = null;

async function fetchOrgId(
  workspaceHost: string,
  token: string,
): Promise<string | null> {
  try {
    const resp = await fetch(
      `${workspaceHost}/api/2.0/preview/scim/v2/Me`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    return resp.headers.get('x-databricks-org-id');
  } catch {
    return null;
  }
}

async function fetchGenieSpaceTitle(
  workspaceHost: string,
  token: string,
  spaceId: string,
): Promise<string | null> {
  try {
    const resp = await fetch(
      `${workspaceHost}/api/2.0/genie/spaces/${spaceId}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!resp.ok) return null;
    const data = (await resp.json()) as { title?: string };
    return data.title ?? null;
  } catch {
    return null;
  }
}

async function resolveResources() {
  if (cachedResources) return cachedResources;

  let workspaceHost: string | null = null;
  let token: string | null = null;
  let orgId: string | null = null;

  try {
    workspaceHost = await getWorkspaceHostname();
    token = await getDatabricksToken();
  } catch {
    console.warn('[Config] Unable to resolve workspace hostname or token for resource links');
  }

  if (workspaceHost && token) {
    orgId = await fetchOrgId(workspaceHost, token);
  }

  const orgQuery = orgId ? `?o=${orgId}` : '';

  const genieSpaceIds = (process.env.GENIE_SPACE_IDS || '')
    .split(',')
    .map((id) => id.trim())
    .filter(Boolean);

  const genieSpaces = await Promise.all(
    genieSpaceIds.map(async (id, idx) => {
      let name = `Genie Space ${idx + 1}`;
      if (workspaceHost && token) {
        const title = await fetchGenieSpaceTitle(workspaceHost, token, id);
        if (title) name = title;
      }
      return {
        id,
        name,
        url: workspaceHost ? `${workspaceHost}/genie/rooms/${id}${orgQuery}` : '',
      };
    }),
  );

  const experimentId = process.env.MLFLOW_EXPERIMENT_ID;
  const mlflowExperiment = experimentId
    ? {
        id: experimentId,
        url: workspaceHost
          ? `${workspaceHost}/ml/experiments/${experimentId}${orgQuery}`
          : '',
      }
    : null;

  cachedResources = { workspaceHost, genieSpaces, mlflowExperiment };
  return cachedResources;
}

/**
 * GET /api/config - Get application configuration
 * Returns feature flags and resource links based on environment configuration
 */
configRouter.get('/', async (_req: Request, res: Response) => {
  const resources = await resolveResources();

  res.json({
    features: {
      chatHistory: isDatabaseAvailable(),
      feedback: !!process.env.MLFLOW_EXPERIMENT_ID,
    },
    resources: {
      genieSpaces: resources.genieSpaces,
      mlflowExperiment: resources.mlflowExperiment,
    },
  });
});
