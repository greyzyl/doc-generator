import type { ReactNode } from 'react';

interface StepBadgeProps {
  done?: boolean;
  active?: boolean;
  children: ReactNode;
}

export function StepBadge({ done, active, children }: StepBadgeProps) {
  const className = done ? 'step-badge done' : active ? 'step-badge active' : 'step-badge';
  return <span className={className}>{children}</span>;
}
