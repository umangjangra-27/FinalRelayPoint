import React, { useEffect, useState } from 'react';
import { api } from '../services/api';
import {
  Finding,
  HandoverReportPayload,
  PriorityLevel,
  ReportDetail,
  ReviewDecisionType,
  ReviewSummary,
} from '../types/api';
import { DeveloperView } from '../components/reports/DeveloperView';
import { TeamLeadView } from '../components/reports/TeamLeadView';
import { EvidenceDrawer } from '../components/evidence/EvidenceDrawer';
import { EditFindingModal } from '../components/reports/EditFindingModal';
import { ReviewHistoryDrawer } from '../components/reports/ReviewHistoryDrawer';
import { FinalizeReportModal } from '../components/reports/FinalizeReportModal';
import { Button } from '../components/ui/Button';
import { ReportReviewStatusBadge } from '../components/ui/Badge';
import { formatDate } from '../utils/formatters';
import {
  UserCheck,
  Code,
  ShieldCheck,
  AlertTriangle,
  ArrowLeft,
  RotateCw,
  Loader2,
  AlertCircle,
  HelpCircle,
  XCircle,
  History,
  CheckCircle2,
} from 'lucide-react';

interface ReportDetailPageProps {
  reportId: string;
  onBack: () => void;
  onSelectRepository?: (repoId: string) => void;
}

export const ReportDetailPage: React.FC<ReportDetailPageProps> = ({
  reportId,
  onBack,
  onSelectRepository,
}) => {
  const [report, setReport] = useState<ReportDetail | null>(null);
  const [activeRole, setActiveRole] = useState<'developer' | 'team_lead'>('developer');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Evidence Drawer state
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [isReverifying, setIsReverifying] = useState(false);

  // Human Review State
  const [editingFinding, setEditingFinding] = useState<Finding | null>(null);
  const [isHistoryDrawerOpen, setIsHistoryDrawerOpen] = useState(false);
  const [isFinalizeModalOpen, setIsFinalizeModalOpen] = useState(false);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  const fetchReport = (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    api
      .getReport(reportId)
      .then((data) => {
        setReport(data);
      })
      .catch((err) => {
        setError(err.detail || 'Could not load handover report.');
      })
      .finally(() => {
        if (!silent) setLoading(false);
      });
  };

  useEffect(() => {
    fetchReport();
  }, [reportId]);

  const handleReverify = () => {
    setIsReverifying(true);
    api
      .verifyReport(reportId)
      .then(() => {
        fetchReport(true);
        setActionSuccess('Deterministic citation audit and SHA-256 integrity reverified.');
        setTimeout(() => setActionSuccess(null), 4000);
      })
      .catch((err) => {
        alert(`Reverification failed: ${err.detail || err.message}`);
      })
      .finally(() => {
        setIsReverifying(false);
      });
  };

  const handleOpenEvidence = (sourceId: string) => {
    setSelectedSourceId(sourceId);
    setIsDrawerOpen(true);
  };

  const handleReviewDecision = async (
    findingId: string,
    decision: ReviewDecisionType,
    comment?: string
  ) => {
    try {
      await api.submitReviewDecision(reportId, {
        finding_id: findingId,
        decision,
        reviewer_name: 'Lead Reviewer (Demo)',
        reviewer_comment: comment || '',
      });
      fetchReport(true);
      setActionSuccess(`Finding ${findingId} marked as ${decision.replace('_', ' ')}.`);
      setTimeout(() => setActionSuccess(null), 3000);
    } catch (err: any) {
      alert(`Failed to save review decision: ${err.detail || err.message}`);
    }
  };

  const handleSaveEdit = async (
    findingId: string,
    updates: { title: string; description: string; priority: PriorityLevel },
    reviewerName: string,
    reviewerComment: string
  ) => {
    await api.submitReviewDecision(reportId, {
      finding_id: findingId,
      decision: 'edited',
      reviewer_name: reviewerName,
      reviewer_comment: reviewerComment,
      updated_finding: updates,
    });
    fetchReport(true);
    setActionSuccess(`Finding ${findingId} updated and recorded in audit log.`);
    setTimeout(() => setActionSuccess(null), 3000);
  };

  const handleFinalize = async (reviewerName: string, notes: string) => {
    await api.finalizeReport(reportId, {
      reviewer_name: reviewerName,
      final_notes: notes,
    });
    fetchReport(true);
    setActionSuccess('Handover report review successfully finalized and signed off!');
    setTimeout(() => setActionSuccess(null), 4000);
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-slate-500">
        <Loader2 className="w-8 h-8 animate-spin text-brand-600 mb-3" />
        <p className="text-sm">Retrieving structured handover report...</p>
      </div>
    );
  }

  if (error || !report) {
    return (
      <div className="rounded-lg bg-rose-50 border border-rose-200 p-6 text-center max-w-lg mx-auto">
        <AlertCircle className="w-8 h-8 text-rose-600 mx-auto mb-2" />
        <h3 className="text-base font-semibold text-rose-900">Failed to Load Report</h3>
        <p className="text-xs text-rose-700 mt-1 mb-4">{error || 'Report not found.'}</p>
        <Button variant="outline" size="sm" onClick={onBack} icon={<ArrowLeft className="w-3.5 h-3.5" />}>
          Back to Reports
        </Button>
      </div>
    );
  }

  const payload: HandoverReportPayload = report.report_data;
  const coverage = payload.coverage;
  const stats = payload.verification_stats || {};
  const reviewSummary: ReviewSummary | undefined = report.review_summary || payload.review_summary || undefined;
  const isFinalized = report.status === 'finalized';
  const totalFindings = reviewSummary?.total_findings || payload.raw_findings?.length || 0;
  const reviewedCount = reviewSummary?.reviewed_count || 0;
  const pendingCount = reviewSummary?.pending_count ?? Math.max(0, totalFindings - reviewedCount);
  const progressPct = totalFindings > 0 ? Math.round((reviewedCount / totalFindings) * 100) : 100;
  const canFinalize = Boolean(reviewSummary?.can_finalize) && !isFinalized;

  return (
    <div className="space-y-6">
      {/* Navigation & Actions Top Bar */}
      <div className="flex items-center justify-between">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-800 transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Back to Reports
        </button>

        <div className="flex items-center gap-2.5">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setIsHistoryDrawerOpen(true)}
            icon={<History className="w-3.5 h-3.5 text-slate-600" />}
            title="Inspect human review history and audit decisions"
          >
            Review Audit Log ({report.review_history?.length || 0})
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={handleReverify}
            isLoading={isReverifying}
            icon={<RotateCw className={`w-3.5 h-3.5 ${isReverifying ? 'animate-spin' : ''}`} />}
            title="Re-run deterministic verification against current stored sources"
          >
            Re-verify Citations
          </Button>
        </div>
      </div>

      {/* Action Notification Banner */}
      {actionSuccess && (
        <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-3 text-xs text-emerald-800 flex items-center justify-between animate-in fade-in slide-in-from-top-1">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
            <span>{actionSuccess}</span>
          </div>
          <button
            onClick={() => setActionSuccess(null)}
            className="text-emerald-700 hover:text-emerald-900 font-bold"
          >
            ×
          </button>
        </div>
      )}

      {/* Human-in-the-Loop Review Progress Banner */}
      <div
        className={`rounded-xl border p-5 shadow-sm space-y-4 ${
          isFinalized
            ? 'bg-emerald-50/50 border-emerald-200'
            : report.status === 'in_review'
            ? 'bg-indigo-50/30 border-indigo-200'
            : 'bg-amber-50/30 border-amber-200'
        }`}
      >
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2.5 flex-wrap">
              <span className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                Human Handover Review
              </span>
              <ReportReviewStatusBadge status={report.status} />
            </div>
            <p className="text-xs text-slate-600 leading-relaxed">
              {isFinalized
                ? 'This report has been reviewed, signed off, and finalized for engineering onboarding. Finding contents are locked.'
                : 'Review, verify, edit, or flag AI-generated findings prior to developer handover finalization.'}
            </p>
          </div>

          {/* Finalize Button / Finalized Badge */}
          <div className="shrink-0 flex items-center gap-3">
            {isFinalized ? (
              <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-100 text-emerald-900 font-semibold text-xs border border-emerald-300">
                <ShieldCheck className="w-4 h-4 text-emerald-700" />
                <span>Finalized & Signed Off</span>
              </span>
            ) : (
              <Button
                variant="primary"
                size="sm"
                disabled={!canFinalize}
                onClick={() => setIsFinalizeModalOpen(true)}
                className={
                  canFinalize
                    ? '!bg-emerald-600 hover:!bg-emerald-700 !border-emerald-600'
                    : 'opacity-60 cursor-not-allowed'
                }
                icon={<ShieldCheck className="w-3.5 h-3.5" />}
                title={
                  canFinalize
                    ? 'Finalize and sign off handover report'
                    : `${pendingCount} finding(s) still require review before finalization`
                }
              >
                Finalize Report {canFinalize ? '' : `(${pendingCount} pending)`}
              </Button>
            )}
          </div>
        </div>

        {/* Progress Bar & Review Metrics */}
        <div className="space-y-2 pt-2 border-t border-slate-200/70">
          <div className="flex items-center justify-between text-xs font-medium text-slate-700">
            <span>
              Review Completion:{' '}
              <strong className="text-slate-900 font-semibold">
                {reviewedCount} of {totalFindings} claims ({progressPct}%)
              </strong>
            </span>
            <span>{isFinalized ? 'Review Locked' : `${pendingCount} pending review`}</span>
          </div>

          <div className="w-full bg-slate-200/80 rounded-full h-2 overflow-hidden">
            <div
              className={`h-full transition-all duration-300 rounded-full ${
                isFinalized
                  ? 'bg-emerald-600'
                  : progressPct === 100
                  ? 'bg-emerald-500'
                  : 'bg-brand-600'
              }`}
              style={{ width: `${progressPct}%` }}
            />
          </div>

          {/* Review Decision Breakdown Pills */}
          <div className="flex items-center gap-3 pt-1 text-[11px] text-slate-600 flex-wrap">
            <span className="inline-flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              Accepted: <strong>{reviewSummary?.accepted_count || 0}</strong>
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-rose-500" />
              Rejected: <strong>{reviewSummary?.rejected_count || 0}</strong>
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-purple-500" />
              Edited: <strong>{reviewSummary?.edited_count || 0}</strong>
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-amber-500" />
              Investigating: <strong>{reviewSummary?.needs_investigation_count || 0}</strong>
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-slate-400" />
              Pending: <strong>{pendingCount}</strong>
            </span>
          </div>
        </div>
      </div>

      {/* Main Report Title Banner */}
      <div className="bg-white rounded-lg border border-slate-200 p-6 shadow-sm space-y-4">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              {onSelectRepository ? (
                <button
                  type="button"
                  onClick={() => onSelectRepository(report.repository_id)}
                  className="font-mono text-xs px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 text-brand-700 font-medium transition-colors"
                  title="View repository activity and history"
                >
                  {payload.repository_name}
                </button>
              ) : (
                <span className="font-mono text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-medium">
                  {payload.repository_name}
                </span>
              )}
              <span className="text-xs text-slate-400">• Generated {formatDate(payload.generated_at)}</span>
              <span className="text-xs text-slate-400 font-mono">• {payload.model_used}</span>
              {payload.model_used?.toLowerCase().includes('mock') && (
                <span className="inline-flex items-center gap-1 font-semibold text-[11px] px-2 py-0.5 rounded bg-amber-100 text-amber-900 border border-amber-300">
                  Demonstration Report
                </span>
              )}
            </div>
            <h2 className="text-xl font-bold text-slate-900 tracking-tight">{payload.title}</h2>
          </div>

          {/* Role Switcher Toggle */}
          <div className="inline-flex p-1 bg-slate-100 rounded-lg border border-slate-200 shrink-0 self-start lg:self-center">
            <button
              onClick={() => setActiveRole('developer')}
              className={`inline-flex items-center gap-2 px-4 py-2 rounded-md text-xs font-semibold transition-all ${
                activeRole === 'developer'
                  ? 'bg-white text-slate-900 shadow-sm'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <Code className="w-3.5 h-3.5 text-brand-600" />
              <span>Developer View</span>
            </button>
            <button
              onClick={() => setActiveRole('team_lead')}
              className={`inline-flex items-center gap-2 px-4 py-2 rounded-md text-xs font-semibold transition-all ${
                activeRole === 'team_lead'
                  ? 'bg-white text-slate-900 shadow-sm'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <UserCheck className="w-3.5 h-3.5 text-indigo-600" />
              <span>Team Lead View</span>
            </button>
          </div>
        </div>

        {/* Verification & Coverage Metrics Bar */}
        <div className="pt-4 border-t border-slate-100 grid grid-cols-2 md:grid-cols-5 gap-3 text-xs">
          <div className="p-2.5 rounded bg-slate-50 border border-slate-200/80">
            <span className="text-[11px] text-slate-500 block">History Coverage</span>
            <span className="font-semibold text-slate-800 text-sm">
              {coverage ? `${coverage.coverage_percentage}%` : 'N/A'}
            </span>
          </div>

          <div className="p-2.5 rounded bg-emerald-50/60 border border-emerald-200/80">
            <span className="text-[11px] text-emerald-700 block flex items-center gap-1">
              <ShieldCheck className="w-3 h-3 text-emerald-600" /> Source Linked
            </span>
            <span className="font-semibold text-emerald-800 text-sm">
              {stats.SOURCE_LINKED || 0} claims
            </span>
          </div>

          <div className="p-2.5 rounded bg-amber-50/60 border border-amber-200/80">
            <span className="text-[11px] text-amber-800 block flex items-center gap-1">
              <AlertTriangle className="w-3 h-3 text-amber-600" /> Needs Review
            </span>
            <span className="font-semibold text-amber-900 text-sm">
              {stats.NEEDS_HUMAN_REVIEW || 0} claims
            </span>
          </div>

          <div className="p-2.5 rounded bg-slate-50 border border-slate-200/80">
            <span className="text-[11px] text-slate-500 block flex items-center gap-1">
              <HelpCircle className="w-3 h-3 text-slate-400" /> No Direct Evidence
            </span>
            <span className="font-semibold text-slate-700 text-sm">
              {stats.INSUFFICIENT_EVIDENCE || 0} claims
            </span>
          </div>

          <div className="p-2.5 rounded bg-rose-50/60 border border-rose-200/80">
            <span className="text-[11px] text-rose-700 block flex items-center gap-1">
              <XCircle className="w-3 h-3 text-rose-600" /> Invalid Citation
            </span>
            <span className="font-semibold text-rose-800 text-sm">
              {stats.INVALID_REFERENCE || 0} claims
            </span>
          </div>
        </div>

        {/* Honest Coverage Warning if Bounded */}
        {coverage && !coverage.is_complete_coverage && (
          <div className="rounded bg-amber-50/90 border border-amber-200 p-3 text-xs text-amber-800 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold">Partial History Coverage ({coverage.coverage_percentage}%)</span>
              <p className="mt-0.5 text-amber-700">
                The repository history exceeded the input character budget. Analyzed {coverage.analyzed_chunks} of {coverage.total_available_chunks} total chunks. Findings reflect prioritized active work and recent commits.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Role-Based View Switch */}
      {activeRole === 'developer' ? (
        <DeveloperView
          data={payload.developer_view}
          onViewEvidence={handleOpenEvidence}
          onReviewDecision={handleReviewDecision}
          onEditFinding={(f) => setEditingFinding(f)}
          isFinalized={isFinalized}
        />
      ) : (
        <TeamLeadView
          data={payload.team_lead_view}
          onViewEvidence={handleOpenEvidence}
          onReviewDecision={handleReviewDecision}
          onEditFinding={(f) => setEditingFinding(f)}
          isFinalized={isFinalized}
        />
      )}

      {/* Interactive Evidence Inspection Drawer */}
      <EvidenceDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        sourceId={selectedSourceId}
        repositoryId={payload.repository_id}
        preloadedItem={
          payload.developer_view?.evidence_appendix?.find((item) => item.source_id === selectedSourceId) || null
        }
      />

      {/* Edit Finding Modal */}
      <EditFindingModal
        isOpen={Boolean(editingFinding)}
        onClose={() => setEditingFinding(null)}
        finding={editingFinding}
        onSave={handleSaveEdit}
      />

      {/* Review History Audit Drawer */}
      <ReviewHistoryDrawer
        isOpen={isHistoryDrawerOpen}
        onClose={() => setIsHistoryDrawerOpen(false)}
        history={report.review_history || []}
        reportTitle={payload.title}
      />

      {/* Finalize Handover Report Modal */}
      <FinalizeReportModal
        isOpen={isFinalizeModalOpen}
        onClose={() => setIsFinalizeModalOpen(false)}
        reportTitle={payload.title}
        reviewedCount={reviewedCount}
        totalCount={totalFindings}
        onFinalize={handleFinalize}
      />
    </div>
  );
};
