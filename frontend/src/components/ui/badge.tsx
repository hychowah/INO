import { cva, type VariantProps } from 'class-variance-authority';
import type { HTMLAttributes } from 'react';
import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium tracking-wide transition-colors',
  {
    variants: {
      variant: {
        default: 'border-sky-400/30 bg-sky-400/10 text-sky-100',
        outline: 'border-white/15 bg-white/5 text-slate-200',
        muted: 'border-slate-800 bg-slate-900 text-slate-300',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  }
);

export type BadgeProps = HTMLAttributes<HTMLDivElement> & VariantProps<typeof badgeVariants>;

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}