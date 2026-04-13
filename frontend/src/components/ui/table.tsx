import * as React from 'react';
import { cn } from '@/lib/utils';

export const Table = React.forwardRef<HTMLTableElement, React.TableHTMLAttributes<HTMLTableElement>>(
  ({ className, ...props }, ref) => {
    return <table ref={ref} className={cn('w-full border-separate border-spacing-0 text-left text-sm', className)} {...props} />;
  }
);

Table.displayName = 'Table';

export const TableHeader = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => {
    return <thead ref={ref} className={cn(className)} {...props} />;
  }
);

TableHeader.displayName = 'TableHeader';

export const TableBody = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => {
    return <tbody ref={ref} className={cn(className)} {...props} />;
  }
);

TableBody.displayName = 'TableBody';

export const TableRow = React.forwardRef<HTMLTableRowElement, React.HTMLAttributes<HTMLTableRowElement>>(
  ({ className, ...props }, ref) => {
    return <tr ref={ref} className={cn('transition-colors', className)} {...props} />;
  }
);

TableRow.displayName = 'TableRow';

export const TableHead = React.forwardRef<HTMLTableCellElement, React.ThHTMLAttributes<HTMLTableCellElement>>(
  ({ className, ...props }, ref) => {
    return <th ref={ref} className={cn('px-4 py-3 text-xs uppercase tracking-[0.2em]', className)} {...props} />;
  }
);

TableHead.displayName = 'TableHead';

export const TableCell = React.forwardRef<HTMLTableCellElement, React.TdHTMLAttributes<HTMLTableCellElement>>(
  ({ className, ...props }, ref) => {
    return <td ref={ref} className={cn('px-4 py-3', className)} {...props} />;
  }
);

TableCell.displayName = 'TableCell';