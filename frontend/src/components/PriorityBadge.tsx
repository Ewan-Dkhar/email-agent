import React from 'react';
import { PriorityTier } from '../types';

interface PriorityBadgeProps {
  priority: PriorityTier;
}

export const PriorityBadge: React.FC<PriorityBadgeProps> = ({ priority }) => {
  const getBadgeStyle = () => {
    switch (priority) {
      case 'P1_CRITICAL':
        return {
          bg: '#fee2e2',
          text: '#991b1b',
          border: '#f87171',
          label: 'P1 CRITICAL',
        };
      case 'P2_ACTIONABLE':
        return {
          bg: '#fef3c7',
          text: '#92400e',
          border: '#fbbf24',
          label: 'P2 ACTIONABLE',
        };
      case 'P3_INFORMATIONAL':
        return {
          bg: '#e0f2fe',
          text: '#075985',
          border: '#38bdf8',
          label: 'P3 INFO',
        };
    }
  };

  const style = getBadgeStyle();

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '2px 8px',
        fontSize: '11px',
        fontWeight: '700',
        borderRadius: '4px',
        backgroundColor: style.bg,
        color: style.text,
        border: `1px solid ${style.border}`,
        letterSpacing: '0.05em',
      }}
    >
      {style.label}
    </span>
  );
};
