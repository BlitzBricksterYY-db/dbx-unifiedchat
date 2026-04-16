const capturedRequests: unknown[] = [];

export function getCapturedRequests() {
  return capturedRequests;
}

export function resetCapturedRequests() {
  capturedRequests.length = 0;
}

export function getLastCapturedRequest() {
  return capturedRequests[capturedRequests.length - 1] ?? null;
}

export function resetMlflowAssessmentStore() {
  return undefined;
}
