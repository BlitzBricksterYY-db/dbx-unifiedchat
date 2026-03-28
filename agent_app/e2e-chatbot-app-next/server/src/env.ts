import dotenv from 'dotenv';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

// Get the directory name of the current module
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Check if running in test mode
const TEST_MODE = process.env.TEST_MODE;

if (!TEST_MODE) {
  const envPath = path.resolve(__dirname, '../../../.env');
  dotenv.config({
    path: envPath,
    override: false, // Don't override environment variables already set (e.g., API_PROXY from start.sh)
  });

  if (!fs.existsSync(envPath)) {
    console.warn(`[env] Expected env file not found at ${envPath}`);
  }
}
