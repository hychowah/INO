import type * as React from 'react';
import { GripVertical } from 'lucide-react';
import * as ResizablePrimitive from 'react-resizable-panels';
import { cn } from '@/lib/utils';

function ResizablePanelGroup({ className, ...props }: React.ComponentProps<typeof ResizablePrimitive.PanelGroup>) {
  return (
    <ResizablePrimitive.PanelGroup
      className={cn('flex h-full w-full data-[panel-group-direction=vertical]:flex-col', className)}
      {...props}
    />
  );
}

const ResizablePanel = ResizablePrimitive.Panel;

function ResizableHandle({ className, withHandle = true, ...props }: React.ComponentProps<typeof ResizablePrimitive.PanelResizeHandle> & { withHandle?: boolean }) {
  return (
    <ResizablePrimitive.PanelResizeHandle
      className={cn(
        'relative flex shrink-0 items-center justify-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
        'data-[panel-group-direction=horizontal]:mx-1 data-[panel-group-direction=horizontal]:w-3 data-[panel-group-direction=horizontal]:cursor-col-resize',
        'data-[panel-group-direction=vertical]:my-1 data-[panel-group-direction=vertical]:h-3 data-[panel-group-direction=vertical]:w-full data-[panel-group-direction=vertical]:cursor-row-resize',
        className,
      )}
      {...props}
    >
      {withHandle ? (
        <span className="flex h-8 w-8 items-center justify-center rounded-full border border-border/70 bg-panel/95 text-muted-foreground shadow-sm">
          <GripVertical className="h-4 w-4 data-[panel-group-direction=vertical]:rotate-90" />
        </span>
      ) : null}
    </ResizablePrimitive.PanelResizeHandle>
  );
}

export { ResizableHandle, ResizablePanel, ResizablePanelGroup };