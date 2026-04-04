/**
 * Database connection pooling using centralized Databricks authentication
 */
import { drizzle } from 'drizzle-orm/postgres-js';
import type postgres from 'postgres';
import * as schema from './schema';
import { getConnectionUrl, getSchemaName } from './connection';
import { getDatabricksToken, invalidateCachedToken } from '@chat-template/auth';

// Connection pool management
let sqlConnection: postgres.Sql | null = null;
let currentToken: string | null = null;

async function invalidatePool(): Promise<void> {
  if (sqlConnection) {
    try {
      await sqlConnection.end({ timeout: 5 });
    } catch { /* best-effort */ }
    sqlConnection = null;
    currentToken = null;
  }
}

async function getConnection(): Promise<postgres.Sql> {
  const { default: postgres } = await import('postgres');
  const freshToken = await getDatabricksToken();

  if (sqlConnection && currentToken !== freshToken) {
    console.log('[DB Pool] Token changed, closing existing connection pool');
    await invalidatePool();
  }

  if (!sqlConnection) {
    const connectionUrl = await getConnectionUrl();
    sqlConnection = postgres(connectionUrl, {
      max: 10,
      idle_timeout: 20,
      connect_timeout: 10,
      max_lifetime: 60 * 10,
    });

    currentToken = freshToken;
    console.log('[DB Pool] Created new connection pool with fresh OAuth token');
  }

  return sqlConnection;
}

function isAuthError(error: unknown): boolean {
  if (error && typeof error === 'object' && 'code' in error) {
    return (error as { code: string }).code === '28P01';
  }
  const msg = error instanceof Error ? error.message : String(error);
  return msg.includes('password authentication failed');
}

async function setSearchPath(sql: postgres.Sql): Promise<void> {
  const schemaName = getSchemaName();
  if (schemaName === 'public') return;

  await sql`SET search_path TO ${sql(schemaName)}, public`;
  console.log(`[DB Pool] Set search_path to include schema '${schemaName}'`);
}

export async function getDb() {
  let sql = await getConnection();

  try {
    await setSearchPath(sql);
  } catch (error) {
    if (isAuthError(error)) {
      console.warn('[DB Pool] Auth error on search_path probe — refreshing pool with new token');
      await invalidatePool();
      invalidateCachedToken();
      sql = await getConnection();
      try {
        await setSearchPath(sql);
      } catch (retryError) {
        const msg = retryError instanceof Error ? retryError.message : String(retryError);
        console.error(`[DB Pool] search_path still failing after token refresh: ${msg}`);
      }
    } else {
      const msg = error instanceof Error ? error.message : String(error);
      console.error(`[DB Pool] Failed to set search_path: ${msg}`);
    }
  }

  return drizzle(sql, { schema });
}
