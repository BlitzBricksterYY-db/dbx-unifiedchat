import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { Suspense, useState } from 'react';
import { useGetSelectionSuspense, useRunEnrichment, useGetEnrichmentStatusSuspense, useListEnrichmentResultsSuspense } from '@/lib/api';
import { selector } from '@/lib/selector';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ArrowLeft, ExternalLink } from 'lucide-react';

export const Route = createFileRoute('/_sidebar/enrichment')({
  component: () => (
    <div>
      <h1 className="text-3xl font-bold mb-6">Enrich Tables</h1>
      <Suspense fallback={<EnrichmentSkeleton />}>
        <EnrichmentView />
      </Suspense>
    </div>
  ),
});

function EnrichmentView() {
  const { data: selection } = useGetSelectionSuspense(selector());
  const [jobId, setJobId] = useState<number | null>(null);
  const [jobUrl, setJobUrl] = useState<string | null>(null);
  const runEnrichmentMutation = useRunEnrichment();
  const navigate = useNavigate();

  const handleRunEnrichment = async () => {
    const result = await runEnrichmentMutation.mutateAsync({
      data: { table_fqns: selection.table_fqns }
    });
    // result now contains: {run_id, job_url, status}
    setJobId(result.run_id);
    setJobUrl(result.job_url);
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Selected Tables ({selection.count})</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2 mb-4">
            {selection.table_fqns.slice(0, 10).map((fqn) => (
              <div key={fqn} className="text-sm p-2 bg-accent rounded">{fqn}</div>
            ))}
            {selection.count > 10 && (
              <p className="text-sm text-muted-foreground">...and {selection.count - 10} more</p>
            )}
          </div>

          {!jobId && (
            <Button onClick={handleRunEnrichment} disabled={runEnrichmentMutation.isPending}>
              {runEnrichmentMutation.isPending ? 'Starting...' : 'Run Enrichment'}
            </Button>
          )}
        </CardContent>
      </Card>

      {jobId && jobUrl && (
        <Suspense fallback={<Skeleton className="h-32 w-full" />}>
          <EnrichmentProgress jobId={jobId} jobUrl={jobUrl} />
        </Suspense>
      )}

      {jobId && (
        <Suspense fallback={<Skeleton className="h-64 w-full" />}>
          <EnrichmentResults />
        </Suspense>
      )}

      <div className="flex gap-4">
        <Button variant="outline" onClick={() => navigate({ to: '/catalog-browser' })}>
          <ArrowLeft size={16} /> Back
        </Button>
        {jobId && (
          <Button onClick={() => navigate({ to: '/graph-explorer' })}>
            Next: Explore Graph →
          </Button>
        )}
      </div>
    </div>
  );
}

function EnrichmentProgress({ jobId, jobUrl }: { jobId: number, jobUrl: string }) {
  const { data: status } = useGetEnrichmentStatusSuspense(jobId, {
    query: {
      refetchInterval: (query) => {
        const data = query.state.data;
        // Poll every 5 seconds if job is still running
        if (data && (data.status === 'pending' || data.status === 'running')) {
          return 5000;
        }
        return false;
      }
    }
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Enrichment Progress</span>
          <a 
            href={jobUrl} 
            target="_blank" 
            rel="noopener noreferrer"
            className="text-sm text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300 flex items-center gap-1 transition-colors"
          >
            View Job in Databricks <ExternalLink size={14} />
          </a>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          <div className="flex justify-between text-sm">
            <span className="font-medium">Status: <span className={
              status.status === 'completed' ? 'text-green-600 dark:text-green-400' :
              status.status === 'failed' ? 'text-red-600 dark:text-red-400' :
              status.status === 'running' ? 'text-blue-600 dark:text-blue-400' :
              'text-slate-600 dark:text-slate-400'
            }>{status.status.toUpperCase()}</span></span>
            <span className="text-slate-600 dark:text-slate-400">Run ID: {status.run_id}</span>
          </div>
          
          {status.life_cycle_state && (
            <div className="text-xs text-slate-600 dark:text-slate-400 bg-slate-50 dark:bg-slate-800 rounded p-2">
              <div>Lifecycle: <span className="font-mono">{status.life_cycle_state}</span></div>
              {status.result_state && (
                <div>Result: <span className="font-mono">{status.result_state}</span></div>
              )}
            </div>
          )}
          
          {status.duration_ms && (
            <div className="text-sm text-slate-600 dark:text-slate-400">
              Duration: <span className="font-semibold">{(status.duration_ms / 1000).toFixed(1)}s</span>
            </div>
          )}
          
          {status.state_message && (
            <p className="text-sm text-slate-600 dark:text-slate-400 italic bg-slate-50 dark:bg-slate-800 rounded p-2">
              {status.state_message}
            </p>
          )}
          
          {status.status === 'failed' && (
            <div className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded p-3 border border-red-200 dark:border-red-800">
              <p className="font-semibold">Enrichment job failed</p>
              <p className="text-xs mt-1">Check the job logs in Databricks for details.</p>
            </div>
          )}
          
          {status.status === 'running' && (
            <div className="flex items-center gap-2 text-sm text-blue-600 dark:text-blue-400">
              <div className="animate-spin h-4 w-4 border-2 border-blue-600 dark:border-blue-400 border-t-transparent rounded-full"></div>
              <span>Job is running...</span>
            </div>
          )}
          
          {status.status === 'completed' && (
            <div className="text-sm text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20 rounded p-3 border border-green-200 dark:border-green-800">
              ✓ Enrichment completed successfully!
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function EnrichmentResults() {
  const { data: results } = useListEnrichmentResultsSuspense(selector());

  return (
    <Card>
      <CardHeader>
        <CardTitle>Enrichment Results</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="rounded-md border">
          <table className="w-full">
            <thead>
              <tr className="border-b">
                <th className="text-left p-3">Table</th>
                <th className="text-right p-3">Columns</th>
                <th className="text-center p-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {results.map((result) => (
                <tr key={result.fqn} className="border-b last:border-0">
                  <td className="p-3 text-sm">{result.fqn}</td>
                  <td className="p-3 text-sm text-right">{result.column_count}</td>
                  <td className="p-3 text-center">
                    {result.enriched ? '✓' : '✗'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function EnrichmentSkeleton() {
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <Skeleton className="h-8 w-48" />
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {[...Array(5)].map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
