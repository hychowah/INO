import * as React from 'react';
import { cn } from '@/lib/utils';

const selectClassName =
  'h-11 w-full rounded-full border border-border bg-background/70 px-4 text-sm text-foreground outline-none transition focus-visible:border-primary/50 focus-visible:ring-2 focus-visible:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-50';

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, ...props }, ref) => {
    return <select ref={ref} className={cn(selectClassName, className)} {...props} />;
  }
);

Select.displayName = 'Select';