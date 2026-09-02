import type { ReactNode } from 'react';
import { Card, CardContent, cn } from '@/components/ui/core';

export type PanelTone = 'cyan' | 'teal' | 'blue' | 'amber' | 'violet' | 'emerald';

const CARD_TONES: Record<PanelTone, React.CSSProperties> = {
  cyan: { borderColor: 'rgba(var(--primary-rgb), 0.28)', borderTopColor: 'var(--primary)', boxShadow: 'inset 0 1px 0 rgba(var(--primary-rgb), 0.18), 0 16px 40px rgba(0, 0, 0, 0.18)' },
  teal: { borderColor: 'rgba(45, 212, 191, 0.24)', borderTopColor: '#2dd4bf', boxShadow: 'inset 0 1px 0 rgba(45, 212, 191, 0.16), 0 16px 40px rgba(0, 0, 0, 0.18)' },
  blue: { borderColor: 'rgba(75, 140, 255, 0.25)', borderTopColor: '#4b8cff', boxShadow: 'inset 0 1px 0 rgba(75, 140, 255, 0.17), 0 16px 40px rgba(0, 0, 0, 0.18)' },
  amber: { borderColor: 'rgba(245, 158, 11, 0.25)', borderTopColor: '#f59e0b', boxShadow: 'inset 0 1px 0 rgba(245, 158, 11, 0.16), 0 16px 40px rgba(0, 0, 0, 0.18)' },
  violet: { borderColor: 'rgba(167, 139, 250, 0.25)', borderTopColor: '#a78bfa', boxShadow: 'inset 0 1px 0 rgba(167, 139, 250, 0.16), 0 16px 40px rgba(0, 0, 0, 0.18)' },
  emerald: { borderColor: 'rgba(52, 211, 153, 0.25)', borderTopColor: '#34d399', boxShadow: 'inset 0 1px 0 rgba(52, 211, 153, 0.16), 0 16px 40px rgba(0, 0, 0, 0.18)' },
};

const ICON_TONES: Record<PanelTone, string> = {
  cyan: 'text-primary bg-primary/[0.08]',
  teal: 'text-teal-400 bg-teal-400/[0.08]',
  blue: 'text-blue-400 bg-blue-400/[0.08]',
  amber: 'text-amber-400 bg-amber-400/[0.08]',
  violet: 'text-violet-400 bg-violet-400/[0.08]',
  emerald: 'text-emerald-400 bg-emerald-400/[0.08]',
};

export function StatCard({
  label,
  value,
  detail,
  icon,
  status,
  tone = 'cyan',
  delay = 0,
}: {
  label: string;
  value: string;
  detail: string;
  icon: ReactNode;
  status?: ReactNode;
  tone?: PanelTone;
  delay?: number;
}) {
  return (
    <Card
      className="metric-enter group relative overflow-hidden border-t-2 transition-[border-color,transform] duration-200 hover:-translate-y-0.5"
      style={{ animationDelay: `${delay}ms`, ...CARD_TONES[tone] }}
    >
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.13em] text-muted-foreground">{label}</p>
            <div className="mt-3 flex items-end gap-3">
              <span className="truncate font-mono text-[2rem] font-semibold leading-none tracking-[-0.06em] text-foreground" title={value}>{value}</span>
              {status}
            </div>
          </div>
          <div className={cn('flex h-10 w-10 shrink-0 aspect-square items-center justify-center rounded-lg border border-current/15 transition-transform duration-200 group-hover:scale-105', ICON_TONES[tone])}>
            {icon}
          </div>
        </div>
        <p className="mt-4 truncate text-xs text-muted-foreground" title={detail}>{detail}</p>
      </CardContent>
    </Card>
  );
}

export function Panel({
  icon,
  title,
  description,
  action,
  alert = false,
  className,
  children,
}: {
  icon?: ReactNode;
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  alert?: boolean;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <div
      className={cn(
        'rounded-xl border p-5 transition-colors duration-300',
        alert ? 'status-pulse border-amber-400/30 bg-amber-400/[0.05]' : 'border-border/80 bg-card/45',
        className,
      )}
    >
      {(icon || title || action) && (
        <div className="flex items-start justify-between gap-4">
          <div className="flex min-w-0 gap-3">
            {icon && <span className="mt-0.5 shrink-0">{icon}</span>}
            <div className="min-w-0">
              {title && <p className="font-medium">{title}</p>}
              {description && <div className="mt-1 text-sm text-muted-foreground">{description}</div>}
            </div>
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </div>
      )}
      {children}
    </div>
  );
}

export function SectionHeading({ title, description }: { title: string; description: string }) {
  return (
    <div>
      <h2 className="text-base font-semibold">{title}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{description}</p>
    </div>
  );
}

export function SmallStat({
  label,
  value,
  caption,
  tone,
}: {
  label: string;
  value: string;
  caption?: string;
  tone?: 'good' | 'warn';
}) {
  return (
    <div className="rounded-lg border border-border/70 bg-background/30 p-3 transition-[border-color,background-color] duration-200 hover:border-primary/25 hover:bg-background/50">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={cn(
          'mt-1 truncate font-mono text-sm font-semibold capitalize',
          tone === 'good' && 'text-emerald-300',
          tone === 'warn' && 'text-amber-300',
        )}
        title={value}
      >
        {value}
      </p>
      {caption && <p className="mt-1 text-[10px] uppercase tracking-wider text-muted-foreground">{caption}</p>}
    </div>
  );
}
