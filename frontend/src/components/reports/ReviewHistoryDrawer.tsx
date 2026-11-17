import React from 'react';
import { ReviewDecisionRecord } from '../../types/api';
import { ReviewDecisionBadge } from '../ui/Badge';
import { Drawer } from '../ui/Drawer';
import { formatDate } from '../../utils/formatters';
import { History, ShieldCheck, User, MessageSquare, FileText } from 'lucide-react';

interface ReviewHistoryDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  history: ReviewDecisionRecord[];
  reportTitle?: string;
}

export const ReviewHistoryDrawer: React.FC<ReviewHistoryDrawerProps> = ({
  isOpen,
  onClose,
  history,
  reportTitle,
}) => {
  // Sort descending by timestamp for chronological audit display
  const sortedHistory = [...history].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );

  return (
    <Drawer isOpen={isOpen} onClose={onClose} title="Review History & Audit Log" widthClass="max-w-xl">
      <div className="space-y-6">
        {/* Header Summary */}
        <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 space-y-2">
          <div className="flex items-center gap-2 text-slate-800">
            <History className="w-4 h-4 text-brand-600" />
            <h4 className="text-xs font-bold uppercase tracking-wider">Audit Trail</h4>
          </div>
          <p className="text-xs text-slate-600">
            Immutable log of all human evaluations, edits, and status transitions for{' '}
            <span className="font-semibold text-slate-800">{reportTitle || 'this report'}</span>.
          </p>
          <div className="pt-2 border-t border-slate-200/80 flex items-center gap-4 text-xs text-slate-500">
            <span>
              Total Decisions:{' '}
              <strong className="text-slate-800 font-semibold">{history.length}</strong>
            </span>
            <span className="text-slate-300">•</span>
            <span className="italic">Single-user demo review model</span>
          </div>
        </div>

        {/* Audit Timeline */}
        {sortedHistory.length === 0 ? (
          <div className="py-12 text-center text-slate-400 space-y-2">
            <FileText className="w-8 h-8 mx-auto text-slate-300" />
            <p className="text-xs">No review decisions recorded yet.</p>
            <p className="text-[11px] text-slate-400">
              Accept, reject, edit, or flag findings in Developer View or Team Lead View.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {sortedHistory.map((item) => {
              const isFinalization = item.item_id === 'REPORT_FINALIZATION';

              if (isFinalization) {
                return (
                  <div
                    key={item.id}
                    className="p-4 rounded-lg bg-emerald-50 border border-emerald-200 space-y-2"
                  >
                    <div className="flex items-center justify-between">
                      <span className="inline-flex items-center gap-1.5 text-xs font-bold text-emerald-800">
                        <ShieldCheck className="w-4 h-4 text-emerald-600" /> Report Finalized
                      </span>
                      <span className="text-[11px] text-emerald-700">{formatDate(item.created_at)}</span>
                    </div>
                    <p className="text-xs text-emerald-900 font-medium">
                      {item.reviewer_comment || 'Handover report review finalized.'}
                    </p>
                    <div className="flex items-center gap-1.5 text-[11px] text-emerald-700">
                      <User className="w-3 h-3" />
                      <span>{item.reviewer_name}</span>
                    </div>
                  </div>
                );
              }

              return (
                <div
                  key={item.id}
                  className="p-4 rounded-lg bg-white border border-slate-200 shadow-sm space-y-3"
                >
                  {/* Top Row: Item ID + Decision Badge + Timestamp */}
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200">
                        {item.item_id}
                      </span>
                      <ReviewDecisionBadge decision={item.decision} />
                    </div>
                    <span className="text-[11px] text-slate-400">{formatDate(item.created_at)}</span>
                  </div>

                  {/* Reviewer Note */}
                  {item.reviewer_comment && (
                    <div className="flex items-start gap-2 text-xs bg-slate-50 p-2.5 rounded border border-slate-200/60 text-slate-700">
                      <MessageSquare className="w-3.5 h-3.5 text-slate-400 shrink-0 mt-0.5" />
                      <p className="leading-relaxed">{item.reviewer_comment}</p>
                    </div>
                  )}

                  {/* Before/After Diff for Edited findings */}
                  {item.decision === 'edited' && item.original_finding && item.updated_finding && (
                    <div className="space-y-2 pt-2 border-t border-slate-100 text-xs">
                      <span className="text-[11px] font-semibold text-purple-800 block">
                        Modifications Applied:
                      </span>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[11px]">
                        <div className="p-2 rounded bg-rose-50/50 border border-rose-200/60 space-y-1">
                          <span className="font-semibold text-rose-800 block">Original AI Draft</span>
                          <p className="text-slate-700 font-medium">{item.original_finding.title}</p>
                          <p className="text-slate-500 line-clamp-3">{item.original_finding.description}</p>
                        </div>
                        <div className="p-2 rounded bg-emerald-50/50 border border-emerald-200/60 space-y-1">
                          <span className="font-semibold text-emerald-800 block">Human Reviewed</span>
                          <p className="text-slate-800 font-medium">{item.updated_finding.title}</p>
                          <p className="text-slate-600 line-clamp-3">{item.updated_finding.description}</p>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Footer: Reviewer identity */}
                  <div className="flex items-center justify-between text-[11px] text-slate-400 pt-1">
                    <span className="flex items-center gap-1">
                      <User className="w-3 h-3 text-slate-400" />
                      <span>{item.reviewer_name}</span>
                    </span>
                    <span className="font-mono text-[10px] text-slate-400">ID: {item.id}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Drawer>
  );
};
