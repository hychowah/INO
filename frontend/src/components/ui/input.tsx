import * as React from 'react';
import { cn } from '@/lib/utils';

const inputClassName =
  'h-11 w-full rounded-full border border-border bg-background/70 px-4 text-sm text-foreground outline-none transition focus-visible:border-primary/50 focus-visible:ring-2 focus-visible:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-50';

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type = 'text', ...props }, ref) => {
    return <input ref={ref} type={type} className={cn(inputClassName, className)} {...props} />;
  }
);

Input.displayName = 'Input';