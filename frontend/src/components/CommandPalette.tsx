import { Search } from 'lucide-react';
import { Command as CommandPrimitive } from 'cmdk';
import type { LucideIcon } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

export type CommandPaletteItem = {
  id: string;
  label: string;
  description: string;
  icon?: LucideIcon;
  keywords?: string[];
  onSelect: () => void;
};

type CommandPaletteProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: CommandPaletteItem[];
};

export function CommandPalette({ open, onOpenChange, items }: CommandPaletteProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl overflow-hidden p-0">
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <DialogDescription className="sr-only">Search surfaces and utility actions.</DialogDescription>
        <CommandPrimitive className="flex w-full flex-col bg-card/95 text-foreground">
          <div className="flex items-center gap-3 border-b border-border/70 px-4 py-4">
            <Search className="h-4 w-4 text-muted-foreground" />
            <CommandPrimitive.Input
              autoFocus
              placeholder="Jump to a surface or action..."
              className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
            />
            <kbd className="hidden rounded-full border border-border/70 bg-secondary/70 px-2 py-1 text-[11px] uppercase tracking-[0.2em] text-muted-foreground sm:inline-flex">
              Ctrl K
            </kbd>
          </div>
          <CommandPrimitive.List className="max-h-[420px] overflow-y-auto p-2">
            <CommandPrimitive.Empty className="px-3 py-8 text-sm text-muted-foreground">
              No matching commands.
            </CommandPrimitive.Empty>
            <CommandPrimitive.Group heading="Navigate" className="overflow-hidden px-1 text-xs uppercase tracking-[0.2em] text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-2">
              {items.map((item) => {
                const Icon = item.icon;
                return (
                  <CommandPrimitive.Item
                    key={item.id}
                    value={`${item.label} ${item.description}`}
                    keywords={item.keywords}
                    onSelect={() => {
                      item.onSelect();
                      onOpenChange(false);
                    }}
                    className={cn(
                      'flex cursor-pointer items-start gap-3 rounded-[22px] px-3 py-3 text-left outline-none transition-colors',
                      'data-[selected=true]:bg-secondary/80 data-[selected=true]:text-foreground'
                    )}
                  >
                    {Icon ? (
                      <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl border border-border/80 bg-panel-muted text-muted-foreground">
                        <Icon className="h-4 w-4" />
                      </span>
                    ) : null}
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium text-foreground">{item.label}</span>
                      <span className="mt-1 block text-sm text-muted-foreground">{item.description}</span>
                    </span>
                  </CommandPrimitive.Item>
                );
              })}
            </CommandPrimitive.Group>
          </CommandPrimitive.List>
        </CommandPrimitive>
      </DialogContent>
    </Dialog>
  );
}