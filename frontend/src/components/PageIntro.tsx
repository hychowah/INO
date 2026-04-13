import type { ReactNode } from 'react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

type PageIntroProps = {
  eyebrow: string;
  title: string;
  description: string;
  aside?: ReactNode;
  className?: string;
};

export function PageIntro({ eyebrow, title, description, aside, className }: PageIntroProps) {
  return (
    <div className={cn('flex flex-col gap-4 rounded-[26px] border border-border/70 bg-panel-muted/80 px-5 py-4 lg:flex-row lg:items-end lg:justify-between', className)}>
      <div className="space-y-3">
        <Badge className="w-fit">{eyebrow}</Badge>
        <div>
          <h2 className="text-[28px] font-semibold tracking-tight text-foreground">{title}</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">{description}</p>
        </div>
      </div>
      {aside ? <div className="flex flex-wrap items-center gap-2">{aside}</div> : null}
    </div>
  );
}