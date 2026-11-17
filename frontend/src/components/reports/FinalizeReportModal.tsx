import React, { useState } from 'react';
import { Button } from '../ui/Button';
import { ShieldCheck, X, AlertTriangle } from 'lucide-react';

interface FinalizeReportModalProps {
  isOpen: boolean;
  onClose: () => void;
  reportTitle: string;
  reviewedCount: number;
  totalCount: number;
  onFinalize: (reviewerName: string, notes: string) => Promise<void>;
}

export const FinalizeReportModal: React.FC<FinalizeReportModalProps> = ({
  isOpen,
  onClose,
  reportTitle,
  reviewedCount,
  totalCount,
  onFinalize,
}) => {
  if (!isOpen) return null;

  const [reviewerName, setReviewerName] = useState('Lead Reviewer (Demo)');
  const [finalNotes, setFinalNotes] = useState(
    'All findings reviewed and verified. Handover report approved for developer onboarding.'
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      await onFinalize(reviewerName.trim() || 'Lead Reviewer (Demo)', finalNotes.trim());
      onClose();
    } catch (err: any) {
      setError(err.detail || err.message || 'Failed to finalize report.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-2xl border border-slate-200 max-w-lg w-full overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-emerald-50/70">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-emerald-100 flex items-center justify-center text-emerald-700">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-900">Finalize Handover Report</h3>
              <p className="text-xs text-slate-500">Sign off and approve for developer handover</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 p-1 rounded-md transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-xs text-rose-800">
              {error}
            </div>
          )}

          <div className="p-3 rounded-lg bg-slate-50 border border-slate-200 space-y-1 text-xs">
            <span className="font-semibold text-slate-800 block">{reportTitle}</span>
            <div className="flex items-center gap-2 text-slate-600">
              <span>
                Review Progress:{' '}
                <strong className="text-emerald-700 font-semibold">
                  {reviewedCount} of {totalCount} claims reviewed (100%)
                </strong>
              </span>
            </div>
          </div>

          <div className="p-3 rounded-lg bg-amber-50/80 border border-amber-200/80 flex items-start gap-2 text-xs text-amber-800">
            <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold block">Finalization Gate</span>
              <p className="text-[11px] text-amber-700 mt-0.5">
                Finalizing will lock all findings against further modification. The report review status will become permanently <strong className="font-semibold">Finalized</strong>.
              </p>
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-700 block">Reviewer Identity</label>
            <input
              type="text"
              value={reviewerName}
              onChange={(e) => setReviewerName(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-brand-500"
              placeholder="Lead Reviewer (Demo)"
              required
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-700 block">Final Handover Notes</label>
            <textarea
              value={finalNotes}
              onChange={(e) => setFinalNotes(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 text-xs rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-brand-500 text-xs font-normal"
              placeholder="Sign-off summary or instructions for incoming engineers"
            />
          </div>

          <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-200">
            <Button type="button" variant="outline" size="sm" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              isLoading={isSubmitting}
              className="!bg-emerald-600 hover:!bg-emerald-700 !border-emerald-600"
              icon={<ShieldCheck className="w-4 h-4" />}
            >
              Confirm & Finalize Report
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};
