import React, { useState } from 'react';
import { Finding, PriorityLevel } from '../../types/api';
import { Button } from '../ui/Button';
import { PriorityBadge } from '../ui/Badge';
import { X, Edit3, History } from 'lucide-react';

interface EditFindingModalProps {
  isOpen: boolean;
  onClose: () => void;
  finding: Finding | null;
  onSave: (
    findingId: string,
    updates: { title: string; description: string; priority: PriorityLevel },
    reviewerName: string,
    reviewerComment: string
  ) => Promise<void>;
}

export const EditFindingModal: React.FC<EditFindingModalProps> = ({
  isOpen,
  onClose,
  finding,
  onSave,
}) => {
  if (!isOpen || !finding) return null;

  const [title, setTitle] = useState(finding.title);
  const [description, setDescription] = useState(finding.description);
  const [priority, setPriority] = useState<PriorityLevel>(finding.priority);
  const [reviewerName, setReviewerName] = useState(finding.reviewer_name || 'Lead Reviewer (Demo)');
  const [reviewerComment, setReviewerComment] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showOriginal, setShowOriginal] = useState(false);

  const originalFinding = finding.original_data || finding;

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setError('Title cannot be empty.');
      return;
    }
    if (!description.trim()) {
      setError('Description cannot be empty.');
      return;
    }

    setIsSaving(true);
    setError(null);
    try {
      await onSave(
        finding.id,
        {
          title: title.trim(),
          description: description.trim(),
          priority,
        },
        reviewerName.trim() || 'Lead Reviewer (Demo)',
        reviewerComment.trim()
      );
      onClose();
    } catch (err: any) {
      setError(err.detail || err.message || 'Failed to save finding edits.');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-2xl border border-slate-200 max-w-2xl w-full overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-slate-50/80">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-purple-100 flex items-center justify-center text-purple-700">
              <Edit3 className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-bold text-slate-900">Edit Finding</h3>
                <span className="font-mono text-xs px-2 py-0.5 rounded bg-slate-200 text-slate-700 font-semibold">
                  {finding.id}
                </span>
              </div>
              <p className="text-xs text-slate-500">
                Modify claim details while preserving evidence citations and original AI draft.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 p-1 rounded-md transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Form */}
        <form onSubmit={handleSave} className="p-6 space-y-4">
          {error && (
            <div className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-xs text-rose-800">
              {error}
            </div>
          )}

          {/* Toggle view original AI finding */}
          <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-700 flex items-center gap-1.5">
                <History className="w-3.5 h-3.5 text-slate-500" /> Original AI Draft
              </span>
              <button
                type="button"
                onClick={() => setShowOriginal(!showOriginal)}
                className="text-[11px] font-medium text-brand-600 hover:text-brand-800 transition-colors"
              >
                {showOriginal ? 'Hide Original' : 'Show Original'}
              </button>
            </div>
            {showOriginal && (
              <div className="text-xs text-slate-600 space-y-1.5 pt-2 border-t border-slate-200">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-slate-800">{originalFinding.title}</span>
                  <PriorityBadge priority={originalFinding.priority} />
                </div>
                <p className="text-slate-600 italic bg-white p-2.5 rounded border border-slate-200/80">
                  {originalFinding.description}
                </p>
              </div>
            )}
          </div>

          {/* Title */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-700 block">Finding Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-brand-500 font-medium"
              placeholder="Concise finding headline"
              required
            />
          </div>

          {/* Priority */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-700 block">Priority Level</label>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value as PriorityLevel)}
              className="w-full px-3 py-2 text-xs rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white"
            >
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-700 block">Detailed Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              className="w-full px-3 py-2 text-xs rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-brand-500 font-normal leading-relaxed"
              placeholder="Refined explanation based on repository activity"
              required
            />
          </div>

          {/* Reviewer Note */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-700 block">
              Reviewer Comment / Rationale <span className="text-slate-400 font-normal">(Optional)</span>
            </label>
            <input
              type="text"
              value={reviewerComment}
              onChange={(e) => setReviewerComment(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-brand-500"
              placeholder="e.g. Corrected module name and raised priority based on latest commits."
            />
          </div>

          {/* Reviewer Identity */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-700 block">
              Reviewer Identity
            </label>
            <input
              type="text"
              value={reviewerName}
              onChange={(e) => setReviewerName(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-brand-500 bg-slate-50"
              placeholder="Lead Reviewer (Demo)"
            />
            <span className="text-[11px] text-slate-400 block">
              Single-user demo identity recorded in review audit log.
            </span>
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-200">
            <Button type="button" variant="outline" size="sm" onClick={onClose} disabled={isSaving}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              isLoading={isSaving}
              icon={<Edit3 className="w-3.5 h-3.5" />}
            >
              Save Reviewed Finding
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};
