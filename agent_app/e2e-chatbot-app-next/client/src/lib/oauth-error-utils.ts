const URL_PATTERN = /https?:\/\/[^\s)]+/i;
const CONNECTION_PATTERNS = [
  /for the connection\s+'([^']+)'/i,
  /connection(?: name)?[:=]\s*["'`]?([^"'`\n]+)["'`]?/i,
  /login to\s+["'`]?([^"'`\n]+)["'`]?/i,
  /authenticate with\s+["'`]?([^"'`\n]+)["'`]?/i,
];

export function isCredentialErrorMessage(error: string): boolean {
  const normalized = error.toLowerCase();
  return (
    normalized.includes('credential') ||
    normalized.includes('oauth') ||
    normalized.includes('login') ||
    normalized.includes('authenticate')
  );
}

export function findLoginURLFromCredentialErrorMessage(
  error: string,
): string | null {
  return error.match(URL_PATTERN)?.[0] ?? null;
}

export function findConnectionNameFromCredentialErrorMessage(
  error: string,
): string | null {
  for (const pattern of CONNECTION_PATTERNS) {
    const match = error.match(pattern);
    if (match?.[1]) {
      return match[1].trim();
    }
  }

  return isCredentialErrorMessage(error) ? 'required connection' : null;
}
