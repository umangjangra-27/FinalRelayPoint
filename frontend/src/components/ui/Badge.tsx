import React from 'react';
import { PriorityLevel, ReviewDecisionType, VerificationStatus } from '../../types/api';
import {
  getPriorityBadgeStyle,
  getReportReviewStatusStyle,
  getReviewDecisionBadgeStyle,
  getVerificationBadgeStyle,
} from '../../utils/formatters';
import {
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
  XCircle,
  Check,
  X,
  Edit3,
  Clock,
  ShieldCheck,
} from 'lucide-react';

interface VerificationBadgeProps {
  status: VerificationStatus;
  showIcon?: boolean;
  className?: string;
}

export const VerificationBadge: React.FC<VerificationBadgeProps> = ({ status, showIcon = true, className = '' }) => {
  const style = getVerificationBadgeStyle(status);

  const renderIcon = () => {
    switch (status) {
      case 'SOURCE_LINKED':
        return <CheckCircle2 className="w-3.5 h-3.5 mr-1" />;
      case 'NEEDS_HUMAN_REVIEW':
        return <AlertTriangle className="w-3.5 h-3.5 mr-1" />;
      case 'INVALID_REFERENCE':
        return <XCircle className="w-3.5 h-3.5 mr-1" />;
      case 'INSUFFICIENT_EVIDENCE':
      default:
        return <HelpCircle className="w-3.5 h-3.5 mr-1" />;
    }
  };

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${style.bg} ${style.text} ${style.border} ${className}`}
      title={`Verification Status: ${style.label}`}
    >
      {showIcon && renderIcon()}
      {style.label}
    </span>
  );
};

interface PriorityBadgeProps {
  priority: PriorityLevel;
  className?: string;
}

export const PriorityBadge: React.FC<PriorityBadgeProps> = ({ priority, className = '' }) => {
  const style = getPriorityBadgeStyle(priority);
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium uppercase tracking-wider border ${style.bg} ${style.text} ${style.border} ${className}`}
    >
      {priority}
    </span>
  );
};

interface TagProps {
  label: string;
  className?: string;
}

export const Tag: React.FC<TagProps> = ({ label, className = '' }) => (
  <span className={`inline-flex items-center px-2 py-0.5 rounded bg-slate-100 text-slate-700 text-xs font-mono border border-slate-200 ${className}`}>
    {label}
  </span>
);

interface ReviewDecisionBadgeProps {
  decision?: ReviewDecisionType | null;
  className?: string;
}

export const ReviewDecisionBadge: React.FC<ReviewDecisionBadgeProps> = ({ decision, className = '' }) => {
  const style = getReviewDecisionBadgeStyle(decision);

  const renderIcon = () => {
    switch (decision) {
      case 'accepted':
        return <Check className="w-3 h-3 mr-1 text-emerald-600" />;
      case 'rejected':
        return <X className="w-3 h-3 mr-1 text-rose-600" />;
      case 'edited':
        return <Edit3 className="w-3 h-3 mr-1 text-purple-600" />;
      case 'needs_investigation':
        return <AlertTriangle className="w-3 h-3 mr-1 text-amber-600" />;
      default:
        return <Clock className="w-3 h-3 mr-1 text-slate-400" />;
    }
  };

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold border ${style.bg} ${style.text} ${style.border} ${className}`}
      title={`Human Review: ${style.label}`}
    >
      {renderIcon()}
      {style.label}
    </span>
  );
};

interface ReportReviewStatusBadgeProps {
  status?: string;
  className?: string;
}

export const ReportReviewStatusBadge: React.FC<ReportReviewStatusBadgeProps> = ({ status, className = '' }) => {
  const style = getReportReviewStatusStyle(status);

  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border ${style.bg} ${style.text} ${style.border} ${className}`}
    >
      {status === 'finalized' && <ShieldCheck className="w-3.5 h-3.5 mr-1 text-emerald-600" />}
      {status === 'in_review' && <Edit3 className="w-3.5 h-3.5 mr-1 text-indigo-600" />}
      {(!status || status === 'pending_review' || status === 'draft') && (
        <Clock className="w-3.5 h-3.5 mr-1 text-amber-600" />
      )}
      {style.label}
    </span>
  );
};
