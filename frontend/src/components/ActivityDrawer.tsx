import { Activity, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import { ActivitySurface } from '@/pages/ActivityPage';

type ActivityDrawerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function ActivityDrawer({ open, onOpenChange }: ActivityDrawerProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="inset-y-3 left-auto right-3 top-3 h-[calc(100vh-1.5rem)] max-w-none translate-x-0 translate-y-0 w-[min(1040px,calc(100vw-1.5rem))] p-0">
          <div className="flex items-center justify-between gap-4 border-b border-border/70 px-6 py-5">
            <div className="min-w-0">
              <div className="flex items-center gap-3">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary">
                  <Activity className="h-5 w-5" />
                </span>
                <div>
                  <DialogTitle className="text-base">Activity log</DialogTitle>
                  <DialogDescription className="mt-1">
                    Inspect operational history without leaving the current surface.
                  </DialogDescription>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Badge variant="outline">Utility drawer</Badge>
              <DialogClose asChild>
                <Button type="button" variant="secondary" size="sm">
                  <X className="h-4 w-4" />
                  Close
                </Button>
              </DialogClose>
            </div>
          </div>

          <ScrollArea className="min-h-0 flex-1 px-6 py-6">
            <ActivitySurface showHeader={false} />
          </ScrollArea>
        </DialogContent>
    </Dialog>
  );
}