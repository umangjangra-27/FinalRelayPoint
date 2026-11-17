import React, { useState } from 'react';
import { Finding, ReviewDecisionType } from '../../types/api';
import { PriorityBadge, ReviewDecisionBadge, VerificationBadge } from '../ui/Badge';
import {
  FileSearch,
  AlertTriangle,
  Check,
  X,
  Edit3,
  HelpCircle,
  MessageSquare,
  Lock,
  History,
} from 'lucide-react';

interface FindingCardProps {
  finding: Finding;
  onViewEvidence: (sourceId: string) => void;
  onReviewDecision?: (findingId: string, decision: ReviewDecisionType, comment?: string) => Promise<void>;
  onEditFinding?: (finding: Finding) => void;
  isFinalized?: boolean;
}

export const FindingCard: React.FC<FindingCardProps> = ({
  finding,
  onViewEvidence,
  onReviewDecision,
  onEditFinding,
  isFinalized = false,
}) => {
  const hasEvidence = finding.evidence_source_ids && finding.evidence_source_ids.length > 0;
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showOriginal, setShowOriginal] = useState(false);

  const handleDecision = async (decision: ReviewDecisionType) => {
    if (!onReviewDecision || isFinalized || isSubmitting) return;
    setIsSubmitting(true);
    try {
      await onReviewDecision(finding.id, decision);
    } finally {
      setIsSubmitting(false);
    }
  };

  const original = finding.original_data;

  return (
    <div
      className={`bg-white rounded-lg border transition-all space-y-3 p-5 shadow-sm ${
        finding.review_decision === 'rejected'
          ? 'border-rose-200 bg-rose-50/20'
          : finding.review_decision === 'accepted'
          ? 'border-emerald-200/80'
          : finding.review_decision === 'edited'
          ? 'border-purple-200/80'
          : 'border-slate-200 hover:border-slate-300'
      }`}
    >
      {/* Top Header Row */}
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-xs font-semibold text-slate-500 uppercase tracking-wide">
              {finding.id}
            </span>
            <PriorityBadge priority={finding.priority} />
            <ReviewDecisionBadge decision={finding.review_decision} />
            {finding.is_edited && (
              <span className="inline-flex items-center gap-1 font-mono text-[10px] px-1.5 py-0.2 rounded bg-purple-100 text-purple-800 font-semibold border border-purple-200">
                <Edit3 className="w-2.5 h-2.5" /> Edited
              </span>
            )}
            <span className="text-xs text-slate-400 capitalize">• {finding.category.replace(/_/g, ' ')}</span>
          </div>
          <h4 className="text-sm font-semibold text-slate-900 leading-snug">
            {showOriginal && original ? original.title : finding.title}
          </h4>
        </div>

        {/* Verification Status Badge */}
        <VerificationBadge status={finding.verification_status} />
      </div>

      {/* Main Narrative Description */}
      <p className="text-xs text-slate-600 leading-relaxed">
        {showOriginal && original ? original.description : finding.description}
      </p>

      {/* Original vs Edited comparison toggle */}
      {finding.is_edited && original && (
        <div className="flex items-center justify-between text-[11px] pt-1">
          <button
            type="button"
            onClick={() => setShowOriginal(!showOriginal)}
            className="inline-flex items-center gap-1 text-purple-700 hover:text-purple-900 font-medium transition-colors"
          >
            <History className="w-3 h-3" />
            <span>{showOriginal ? 'Show Edited Version' : 'View Original AI Draft'}</span>
          </button>
          {showOriginal && (
            <span className="text-rose-600 font-mono text-[10px] bg-rose-50 px-1.5 py-0.5 rounded border border-rose-200">
              Showing unedited AI text
            </span>
          )}
        </div>
      )}

      {/* Reviewer Comment Note if present */}
      {finding.review_comment && (
        <div className="rounded bg-slate-50 border border-slate-200/80 p-2 text-xs text-slate-700 flex items-start gap-1.5">
          <MessageSquare className="w-3.5 h-3.5 text-slate-400 shrink-0 mt-0.5" />
          <div className="leading-tight">
            <span className="font-semibold text-slate-800 mr-1">
              {finding.reviewer_name || 'Reviewer'}:
            </span>
            <span className="text-slate-600">{finding.review_comment}</span>
          </div>
        </div>
      )}

      {/* Temporal Conflict Alert */}
      {finding.temporal_conflict_detected && (
        <div className="rounded bg-amber-50 border border-amber-200/80 p-2.5 text-xs text-amber-800 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold block">Temporal Discrepancy Flagged</span>
            <p className="text-[11px] text-amber-700 mt-0.5">{finding.verification_notes}</p>
          </div>
        </div>
      )}

      {/* Evidence Citations Footer */}
      <div className="pt-2 border-t border-slate-100 flex items-center justify-between text-xs">
        <div className="flex items-center gap-2">
          <span className="text-slate-400">Confidence:</span>
          <span className="font-medium text-slate-700 capitalize">{finding.confidence}</span>
        </div>

        {hasEvidence ? (
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[11px] text-slate-400">Cited Evidence:</span>
            {finding.evidence_source_ids.map((sid) => (
              <button
                key={sid}
                onClick={() => onViewEvidence(sid)}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-brand-50 hover:bg-brand-100 text-brand-700 font-mono text-[11px] font-medium border border-brand-200 transition-colors"
                title={`Inspect supporting evidence ${sid}`}
              >
                <FileSearch className="w-3 h-3 text-brand-600" />
                <span>{sid}</span>
              </button>
            ))}
          </div>
        ) : (
          <span className="text-[11px] text-slate-400 italic">No supporting sources cited</span>
        )}
      </div>

      {/* Human Review Action Toolbar */}
      {onReviewDecision && (
        <div className="pt-2.5 border-t border-slate-100 flex items-center justify-between gap-2 text-xs">
          <span className="text-[11px] font-medium text-slate-500 flex items-center gap-1">
            {isFinalized ? (
              <>
                <Lock className="w-3 h-3 text-slate-400" /> Review Locked
              </>
            ) : (
              'Review Action:'
            )}
          </span>

          {!isFinalized ? (
            <div className="flex items-center gap-1.5 flex-wrap">
              {/* Accept */}
              <button
                type="button"
                onClick={() => handleDecision('accepted')}
                disabled={isSubmitting}
                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-semibold transition-all border ${
                  finding.review_decision === 'accepted'
                    ? 'bg-emerald-600 text-white border-emerald-600 shadow-xs'
                    : 'bg-white hover:bg-emerald-50 text-slate-700 hover:text-emerald-800 border-slate-200 hover:border-emerald-300'
                }`}
                title="Accept finding as accurate"
              >
                <Check className="w-3 h-3" />
                <span>Accept</span>
              </button>

              {/* Reject */}
              <button
                type="button"
                onClick={() => handleDecision('rejected')}
                disabled={isSubmitting}
                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-semibold transition-all border ${
                  finding.review_decision === 'rejected'
                    ? 'bg-rose-600 text-white border-rose-600 shadow-xs'
                    : 'bg-white hover:bg-rose-50 text-slate-700 hover:text-rose-800 border-slate-200 hover:border-rose-300'
                }`}
                title="Reject finding as inaccurate or obsolete"
              >
                <X className="w-3 h-3" />
                <span>Reject</span>
              </button>

              {/* Needs Investigation */}
              <button
                type="button"
                onClick={() => handleDecision('needs_investigation')}
                disabled={isSubmitting}
                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-semibold transition-all border ${
                  finding.review_decision === 'needs_investigation'
                    ? 'bg-amber-500 text-white border-amber-500 shadow-xs'
                    : 'bg-white hover:bg-amber-50 text-slate-700 hover:text-amber-800 border-slate-200 hover:border-amber-300'
                }`}
                title="Flag finding as requiring deeper investigation"
              >
                <HelpCircle className="w-3 h-3" />
                <span>Investigate</span>
              </button>

              {/* Edit */}
              {onEditFinding && (
                <button
                  type="button"
                  onClick={() => onEditFinding(finding)}
                  disabled={isSubmitting}
                  className={`inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-semibold transition-all border ${
                    finding.review_decision === 'edited'
                      ? 'bg-purple-600 text-white border-purple-600 shadow-xs'
                      : 'bg-white hover:bg-purple-50 text-slate-700 hover:text-purple-800 border-slate-200 hover:border-purple-300'
                  }`}
                  title="Edit title, description, or priority"
                >
                  <Edit3 className="w-3 h-3" />
                  <span>Edit</span>
                </button>
              )}
            </div>
          ) : (
            <span className="text-[11px] text-slate-400 italic">Report finalized</span>
          )}
        </div>
      )}
    </div>
  );
};
