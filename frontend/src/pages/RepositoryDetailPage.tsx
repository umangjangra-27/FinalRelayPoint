import React, { useEffect, useState } from 'react';
import { api } from '../services/api';
import { ActivityItem, ReportSummary, Repository, RepositoryChangesSummary, SourceChunk, SyncCheckpoint } from '../types/api';
import { Button } from '../components/ui/Button';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/Card';
import { formatDate, timeAgo, truncateSha } from '../utils/formatters';
import { EvidenceDrawer } from '../components/evidence/EvidenceDrawer';
import {
  GitBranch,
  ExternalLink,
  DownloadCloud,
  Sparkles,
  Layers,
  Clock,
  FileText,
  AlertCircle,
  ArrowLeft,
  Loader2,
  CheckCircle2,
  RefreshCw,
  Check,
} from 'lucide-react';

interface RepositoryDetailPageProps {
  repositoryId: string;
  onBack: () => void;
  onOpenReport: (reportId: string) => void;
}

export const RepositoryDetailPage: React.FC<RepositoryDetailPageProps> = ({
  repositoryId,
  onBack,
  onOpenReport,
}) => {
  const [repo, setRepo] = useState<Repository | null>(null);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [sources, setSources] = useState<SourceChunk[]>([]);
  const [totalSources, setTotalSources] = useState(0);
  const [checkpoint, setCheckpoint] = useState<SyncCheckpoint | null>(null);
  const [changes, setChanges] = useState<RepositoryChangesSummary | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Ingestion & Sync & Analysis state
  const [isIngesting, setIsIngesting] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [ingestionMessage, setIngestionMessage] = useState<string | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);

  // Evidence Drawer state
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  const loadAll = () => {
    setLoading(true);
    setError(null);

    Promise.all([
      api.getRepository(repositoryId),
      api.getRepositoryActivity(repositoryId, 25),
      api.listRepositoryReports(repositoryId),
      api.getRepositorySources(repositoryId, { limit: 15 }),
      api.getSyncStatus(repositoryId).catch(() => null),
      api.getChangesSinceLastHandover(repositoryId).catch(() => null),
    ])
      .then(([repoData, actData, repData, srcData, cpData, chData]) => {
        setRepo(repoData);
        setActivity(actData);
        setReports(repData);
        setSources(srcData.sources);
        setTotalSources(srcData.total);
        setCheckpoint(cpData);
        setChanges(chData);
      })
      .catch((err) => {
        setError(err.detail || 'Could not load repository data.');
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    loadAll();
  }, [repositoryId]);

  const handleSync = async (forceFull = false) => {
    setIsSyncing(true);
    setSyncMessage(null);
    try {
      const res = await api.syncRepository(repositoryId, forceFull);
      const detailMsg = res.is_incremental
        ? `Incremental sync complete: ${res.new_commits_count || res.chunks_created} new commits, ${res.updated_prs_count || 0} updated PRs, ${res.updated_issues_count || 0} updated issues.`
        : `Full sync complete: ${res.chunks_created} chunks stored (${res.duplicates_skipped} duplicates skipped).`;
      setSyncMessage(detailMsg);
      loadAll();
    } catch (err: any) {
      alert(`Sync failed: ${err.detail || err.message}`);
    } finally {
      setIsSyncing(false);
    }
  };

  const handleIngest = async () => {
    setIsIngesting(true);
    setIngestionMessage(null);
    try {
      const res = await api.ingestRepository(repositoryId);
      setIngestionMessage(`Successfully ingested ${res.chunks_created} new chunks (${res.duplicates_skipped} duplicates skipped).`);
      loadAll();
    } catch (err: any) {
      alert(`Ingestion failed: ${err.detail || err.message}`);
    } finally {
      setIsIngesting(false);
    }
  };

  const handleAnalyze = async () => {
    setIsAnalyzing(true);
    setAnalysisError(null);
    try {
      const res = await api.analyzeRepository(repositoryId);
      onOpenReport(res.report_id);
    } catch (err: any) {
      setAnalysisError(err.detail || 'Analysis failed. Please verify GEMINI_API_KEY is configured.');
    } finally {
      setIsAnalyzing(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-slate-500">
        <Loader2 className="w-8 h-8 animate-spin text-brand-600 mb-3" />
        <p className="text-sm">Loading repository intelligence...</p>
      </div>
    );
  }

  if (error || !repo) {
    return (
      <div className="rounded-lg bg-rose-50 border border-rose-200 p-6 text-center max-w-lg mx-auto">
        <AlertCircle className="w-8 h-8 text-rose-600 mx-auto mb-2" />
        <h3 className="text-base font-semibold text-rose-900">Repository Unavailable</h3>
        <p className="text-xs text-rose-700 mt-1 mb-4">{error || 'Repository record not found.'}</p>
        <Button variant="outline" size="sm" onClick={onBack} icon={<ArrowLeft className="w-3.5 h-3.5" />}>
          Back to Repositories
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Back button */}
      <button
        onClick={onBack}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-800 transition-colors"
      >
        <ArrowLeft className="w-3.5 h-3.5" /> Back to Repositories
      </button>

      {/* Main Repository Header Card */}
      <div className="bg-white rounded-lg border border-slate-200 p-6 shadow-sm space-y-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-semibold uppercase">
                {repo.provider}
              </span>
              <span className="text-xs text-slate-400 font-mono flex items-center gap-1">
                <GitBranch className="w-3.5 h-3.5" /> {repo.default_branch}
              </span>
            </div>
            <h2 className="text-2xl font-bold text-slate-900 tracking-tight">{repo.full_name}</h2>
            {repo.description && <p className="text-xs text-slate-600 max-w-3xl">{repo.description}</p>}
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-2.5 shrink-0 flex-wrap">
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleSync(false)}
              isLoading={isSyncing}
              icon={<RefreshCw className={`w-3.5 h-3.5 ${isSyncing ? 'animate-spin' : 'text-brand-600'}`} />}
              title="Pull new commits, updated PRs and issues since last sync"
            >
              Sync Changes
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={handleIngest}
              isLoading={isIngesting || isSyncing}
              icon={<DownloadCloud className="w-3.5 h-3.5 text-slate-500" />}
              title="Perform full repository re-ingestion"
            >
              Full Ingest
            </Button>

            <Button
              variant="primary"
              size="sm"
              onClick={handleAnalyze}
              isLoading={isAnalyzing}
              disabled={totalSources === 0}
              icon={<Sparkles className="w-4 h-4 text-white" />}
              title={totalSources === 0 ? 'Ingest history before analyzing' : 'Generate AI Handover Report'}
            >
              Generate Handover
            </Button>

            <a
              href={repo.repository_url}
              target="_blank"
              rel="noopener noreferrer"
              className="p-2 rounded-md border border-slate-200 text-slate-500 hover:text-slate-800 hover:bg-slate-50 transition-colors"
              title="Open repository on GitHub"
            >
              <ExternalLink className="w-4 h-4" />
            </a>
          </div>
        </div>

        {/* Feedback Messages */}
        {syncMessage && (
          <div className="rounded bg-sky-50 border border-sky-200 p-3 text-xs text-sky-900 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-sky-600 shrink-0" />
            <span>{syncMessage}</span>
          </div>
        )}

        {ingestionMessage && (
          <div className="rounded bg-emerald-50 border border-emerald-200 p-3 text-xs text-emerald-800 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
            <span>{ingestionMessage}</span>
          </div>
        )}

        {analysisError && (
          <div className="rounded bg-rose-50 border border-rose-200 p-3 text-xs text-rose-800 flex items-start gap-2">
            <AlertCircle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold">Analysis Notice</span>
              <p className="mt-0.5 text-rose-700">{analysisError}</p>
            </div>
          </div>
        )}

        {/* Stats Row */}
        <div className="pt-4 border-t border-slate-100 grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
          <div>
            <span className="text-slate-400 block">Sanitized Sources:</span>
            <span className="font-semibold text-slate-800 text-sm">{totalSources} stored</span>
          </div>
          <div>
            <span className="text-slate-400 block">Generated Reports:</span>
            <span className="font-semibold text-slate-800 text-sm">{reports.length} reports</span>
          </div>
          <div>
            <span className="text-slate-400 block">Connected:</span>
            <span className="text-slate-700">{formatDate(repo.created_at)}</span>
          </div>
          <div>
            <span className="text-slate-400 block">Last Activity Sync:</span>
            <span className="text-slate-700">{timeAgo(repo.updated_at)}</span>
          </div>
        </div>
      </div>

      {/* Synchronization & Changes Card */}
      <div className="bg-white rounded-lg border border-slate-200 p-5 shadow-sm space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <RefreshCw className="w-4 h-4 text-brand-600" />
            <h3 className="text-sm font-semibold text-slate-900">Incremental Synchronization & Handover Delta</h3>
          </div>
          {checkpoint && (
            <div className="flex items-center gap-2">
              <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${
                checkpoint.sync_status === 'success' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'
              }`}>
                {checkpoint.sync_status === 'success' ? 'Synchronized' : checkpoint.sync_status}
              </span>
              <span className="text-xs text-slate-400">
                Last synced: {timeAgo(checkpoint.last_sync_at)}
              </span>
            </div>
          )}
        </div>

        {changes ? (
          changes.has_changes ? (
            <div className="bg-amber-50/70 border border-amber-200/80 rounded-md p-3.5 text-xs text-amber-900 space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-semibold flex items-center gap-1.5 text-amber-950">
                  <AlertCircle className="w-4 h-4 text-amber-600" />
                  {changes.total_changes} new change{changes.total_changes !== 1 ? 's' : ''} detected since last handover
                </span>
                <span className="text-[11px] text-amber-800 font-mono">
                  {changes.new_commits.length} commits • {changes.updated_prs.length} PRs • {changes.updated_issues.length} issues
                </span>
              </div>
              <p className="text-amber-800">{changes.summary}</p>
              {changes.new_commits.length > 0 && (
                <div className="pt-2 border-t border-amber-200/60 flex flex-wrap gap-2 text-[11px]">
                  <span className="font-medium text-amber-950">Latest commits:</span>
                  {changes.new_commits.slice(0, 3).map((c, i) => (
                    <span key={i} className="bg-white/80 px-2 py-0.5 rounded border border-amber-200 font-mono text-[10px]">
                      {truncateSha(c.sha || '')} {c.message?.split('\n')[0].slice(0, 40)}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="bg-emerald-50/70 border border-emerald-200/80 rounded-md p-3.5 text-xs text-emerald-900 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Check className="w-4 h-4 text-emerald-600 shrink-0" />
                <span>Up to date: No new commits or issue updates recorded since the last handover report.</span>
              </div>
              <span className="text-[11px] text-emerald-700 font-medium">Fully Grounded</span>
            </div>
          )
        ) : (
          <div className="text-xs text-slate-400 italic">
            Checkpoints track incremental activity to prevent redundant GitHub calls.
          </div>
        )}
      </div>

      {/* Reports Section */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-brand-600" />
            <CardTitle>Synthesized Handover Reports ({reports.length})</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {reports.length > 0 ? (
            <div className="divide-y divide-slate-100">
              {reports.map((rep) => (
                <div
                  key={rep.id}
                  className="p-4 flex items-center justify-between hover:bg-slate-50 transition-colors"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => onOpenReport(rep.id)}
                        className="text-sm font-semibold text-slate-900 hover:text-brand-600 hover:underline"
                      >
                        {rep.title}
                      </button>
                      <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">
                        {rep.model_used || 'Gemini'}
                      </span>
                    </div>
                    <p className="text-xs text-slate-400">Created {formatDate(rep.created_at)}</p>
                  </div>

                  <div className="flex items-center gap-3">
                    {rep.verification_stats && (
                      <div className="hidden sm:flex items-center gap-2 text-xs">
                        <span className="text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                          {rep.verification_stats.SOURCE_LINKED || 0} Linked
                        </span>
                        {rep.verification_stats.NEEDS_HUMAN_REVIEW ? (
                          <span className="text-amber-800 bg-amber-50 px-2 py-0.5 rounded border border-amber-200">
                            {rep.verification_stats.NEEDS_HUMAN_REVIEW} Review
                          </span>
                        ) : null}
                      </div>
                    )}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onOpenReport(rep.id)}
                    >
                      Open Report
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="p-8 text-center text-xs text-slate-500">
              <Sparkles className="w-6 h-6 text-slate-300 mx-auto mb-2" />
              <p>No handover reports synthesized yet for this repository.</p>
              <p className="text-slate-400 mt-1">Click "Generate Handover" above to analyze the repository history.</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Two Column Layout: Ingested Sources & Activity Timeline */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Ingested Sources Snippet */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Layers className="w-4 h-4 text-indigo-600" />
              <CardTitle>Ingested Source Chunks ({totalSources})</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {sources.length > 0 ? (
              <div className="divide-y divide-slate-100 max-h-96 overflow-y-auto">
                {sources.map((src) => (
                  <div
                    key={src.id}
                    className="p-3.5 flex items-center justify-between text-xs hover:bg-slate-50 transition-colors"
                  >
                    <div className="space-y-1 pr-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[11px] font-semibold text-slate-700">
                          {src.id}
                        </span>
                        <span className="capitalize px-1.5 py-0.2 rounded bg-slate-100 text-slate-600 text-[10px]">
                          {src.source_type}
                        </span>
                        {src.source_external_id && (
                          <span className="font-mono text-slate-400 text-[10px]">
                            #{truncateSha(src.source_external_id, 8)}
                          </span>
                        )}
                      </div>
                      <p className="text-slate-500 line-clamp-1 font-mono text-[11px]">
                        {src.content}
                      </p>
                    </div>

                    <button
                      onClick={() => {
                        setSelectedSourceId(src.id);
                        setIsDrawerOpen(true);
                      }}
                      className="shrink-0 px-2.5 py-1 rounded border border-slate-200 text-slate-700 hover:bg-slate-100 text-xs font-medium"
                    >
                      Inspect
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-6 text-center text-xs text-slate-400 italic">
                No sources ingested. Click "Ingest History" to pull commits, issues, and PRs.
              </div>
            )}
          </CardContent>
        </Card>

        {/* Real Activity Timeline */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-slate-700" />
              <CardTitle>Recent Project Activity ({activity.length})</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {activity.length > 0 ? (
              <div className="divide-y divide-slate-100 max-h-96 overflow-y-auto">
                {activity.map((item, idx) => (
                  <div key={idx} className="p-3.5 text-xs hover:bg-slate-50 transition-colors space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="capitalize px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 text-[10px] font-medium">
                        {item.source_type}
                      </span>
                      <span className="text-slate-400 text-[11px]">{timeAgo(item.timestamp)}</span>
                    </div>
                    <p className="font-medium text-slate-800 line-clamp-1">{item.title}</p>
                    <div className="flex items-center justify-between text-[11px] text-slate-400">
                      <span>By {item.author}</span>
                      {item.source_url && (
                        <a
                          href={item.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-brand-600 hover:underline inline-flex items-center gap-0.5"
                        >
                          GitHub <ExternalLink className="w-3 h-3" />
                        </a>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-6 text-center text-xs text-slate-400 italic">
                No activity stream records yet. Ingest history to populate activity.
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Evidence Drawer */}
      <EvidenceDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        sourceId={selectedSourceId}
        repositoryId={repositoryId}
      />
    </div>
  );
};
