// IMPORTANT: Load environment variables FIRST, before any other imports
// This ensures env vars are available when other modules are initialized
import { config } from 'dotenv';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Load environment variables from project root
// When running with tsx, __dirname is scripts under e2e-chatbot-app-next.
// The shared deployment env lives in the parent agent_app directory.
const projectRoot = join(__dirname, '..');
const envPath = join(projectRoot, '..', '.env');
config({
  path: envPath,
});

// Now import other modules that depend on environment variables
import {
  isDatabaseAvailable,
  getSchemaName,
  getConnectionUrl,
} from '@chat-template/db';

async function main() {
  const { default: postgres } = await import('postgres');
  console.log('🔄 Running database migration...');

  // Require database configuration
  if (!isDatabaseAvailable()) {
    console.warn('⚠️ Database configuration not found!');
    console.warn(
      'ℹ️ Please set PGDATABASE/PGHOST/PGUSER or POSTGRES_URL environment variables to run migrations.',
    );
    console.warn('💡 Skipping migrations in ephemeral mode...');
    process.exit(0);
  }

  console.log('📊 Database configuration detected, running migrations...');

  const schemaName = getSchemaName();
  console.log(`🗃️ Using database schema: ${schemaName}`);

  // Create custom schema if needed
  const connectionUrl = await getConnectionUrl();
  try {
    const schemaConnection = postgres(connectionUrl, { max: 1 });

    console.log(`📁 Creating schema '${schemaName}' if it doesn't exist...`);
    await schemaConnection`CREATE SCHEMA IF NOT EXISTS ${schemaConnection(schemaName)}`;
    console.log(`✅ Schema '${schemaName}' ensured to exist`);

    await schemaConnection.end();
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    console.warn(`⚠️ Schema creation warning:`, errorMessage);
    // Continue with migration even if schema creation had issues
  }

  try {
    // Use drizzle-orm migrate to run SQL migration files
    console.log('🔄 Running SQL migrations from migration files...');

    // Create database connection for running migrations
    const migrationConnectionUrl = await getConnectionUrl();
    const migrationConnection = postgres(migrationConnectionUrl, { max: 1 });

    // Import the migrate function from drizzle-orm
    const { drizzle } = await import('drizzle-orm/postgres-js');
    const { migrate } = await import('drizzle-orm/postgres-js/migrator');

    // Create drizzle instance
    const db = drizzle(migrationConnection);

    // Run migrations from the migrations folder
    const projectRoot = join(__dirname, '..');
    const migrationsFolder = join(projectRoot, 'packages', 'db', 'migrations');

    console.log('📂 Migrations folder:', migrationsFolder);
    console.log('🔄 Applying pending migrations...');

    const migrationsTableName = '__drizzle_migrations';

    // Sync the migrations table sequence only if the table already exists.
    // On a fresh database the table is created by `migrate()` below.
    const [tableExists] = await migrationConnection<{ exists: boolean }[]>`
      SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = ${schemaName}
          AND table_name   = ${migrationsTableName}
      ) AS exists
    `;

    if (tableExists?.exists) {
      const [sequenceRow] = await migrationConnection<
        { sequence_name: string | null }[]
      >`
        SELECT pg_get_serial_sequence(
          ${`${schemaName}.${migrationsTableName}`},
          'id'
        ) AS sequence_name
      `;

      if (sequenceRow?.sequence_name) {
        const [maxIdRow] = await migrationConnection<{ max_id: number }[]>`
          SELECT COALESCE(MAX(id), 0)::int AS max_id
          FROM ${migrationConnection(schemaName)}.${migrationConnection(migrationsTableName)}
        `;

        const maxId = maxIdRow?.max_id ?? 0;
        await migrationConnection`
          SELECT setval(
            ${sequenceRow.sequence_name},
            GREATEST(${maxId}, 1),
            ${maxId > 0}
          )
        `;
        console.log(
          `🔧 Synced ${schemaName}.${migrationsTableName} sequence to max id ${maxId}`,
        );
      }
    } else {
      console.log(
        `ℹ️ ${schemaName}.${migrationsTableName} does not exist yet — skipping sequence sync`,
      );
    }

    await migrate(db, {
      migrationsFolder,
      migrationsSchema: schemaName,
      migrationsTable: migrationsTableName,
    });

    console.log('✅ All migrations applied successfully');

    // Close the connection
    await migrationConnection.end();

    console.log('✅ Database migration completed successfully');
  } catch (error) {
    console.log('error', error);
    const errorMessage = error instanceof Error ? error.message : String(error);
    console.error('❌ Database migration failed:', errorMessage);
    process.exit(1);
  }
}

main().catch((error) => {
  const errorMessage = error instanceof Error ? error.message : String(error);
  console.error('❌ Migration script failed:', errorMessage);
  process.exit(1);
});
