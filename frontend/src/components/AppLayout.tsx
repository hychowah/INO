import type { ReactNode } from 'react';
import { ArrowUpRight, Search, Sparkles } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { Link, useInRouterContext } from 'react-router-dom';
import { isNavItemActive, primaryNavItems, resolveActiveNavItem, resolveBackendHref, resolvePreferredNavHref, utilityNavItems } from '@/lib/navigation';

type AppLayoutProps = {
  active: string;
  children: ReactNode;
  activityDrawerOpen?: boolean;
  onOpenActivityDrawer?: () => void;
  onOpenCommandPalette?: () => void;
};

export function AppLayout({ active, children, activityDrawerOpen = false, onOpenActivityDrawer, onOpenCommandPalette }: AppLayoutProps) {
  const inRouterContext = useInRouterContext();
  const currentNavItem = resolveActiveNavItem(active);

  function renderNavLink(kind: 'primary' | 'utility') {
    const items = kind === 'primary' ? primaryNavItems : utilityNavItems;

    return items.map((item) => {
      const Icon = item.icon;
      const drawerBackedItem = item.href === '/actions' && Boolean(onOpenActivityDrawer) && active !== '/actions';
      const isActive = drawerBackedItem ? activityDrawerOpen : isNavItemActive(active, item);
      const targetHref = resolvePreferredNavHref(active, item.href);
      const className = cn(
        'group flex w-full items-center gap-3 rounded-[22px] border px-3 py-3 text-left transition-all',
        isActive
          ? 'border-primary/20 bg-primary/10 text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]'
          : 'border-transparent bg-transparent text-muted-foreground hover:border-border/70 hover:bg-secondary/55 hover:text-foreground'
      );

      const content = (
        <>
          <span
            className={cn(
              'flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border transition-colors',
              isActive
                ? 'border-primary/20 bg-primary/15 text-primary'
                : 'border-border/80 bg-panel-muted text-muted-foreground group-hover:text-foreground'
            )}
          >
            <Icon className="h-4 w-4" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold tracking-tight">{item.label}</span>
            <span className="mt-0.5 block text-xs text-muted-foreground">{item.description}</span>
          </span>
          <ArrowUpRight className={cn('h-4 w-4 shrink-0 transition-opacity', isActive ? 'opacity-100' : 'opacity-0 group-hover:opacity-60')} />
        </>
      );

      if (drawerBackedItem) {
        return (
          <button key={item.href} type="button" onClick={onOpenActivityDrawer} className={className}>
            {content}
          </button>
        );
      }

      if (inRouterContext) {
        return (
          <Link key={item.href} to={targetHref} className={className}>
            {content}
          </Link>
        );
      }

      return (
        <a key={item.href} href={resolveBackendHref(targetHref)} className={className}>
          {content}
        </a>
      );
    });
  }

  return (
    <div className="h-screen overflow-hidden bg-background text-foreground">
      <div className="grid h-full w-full grid-cols-[minmax(240px,280px)_minmax(0,1fr)] gap-3 p-3">
        <aside className="flex h-full flex-col rounded-[30px] border border-border/70 bg-panel/92 px-4 py-5 shadow-shell backdrop-blur-xl">
          <div className="space-y-4 px-2 pb-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.32em] text-muted-foreground">Learning Agent</div>
                <h1 className="mt-2 text-xl font-semibold tracking-tight text-foreground">Operations Console</h1>
              </div>
              <span className="flex h-11 w-11 items-center justify-center rounded-2xl border border-primary/15 bg-primary/10 text-primary">
                <Sparkles className="h-5 w-5" />
              </span>
            </div>
            <p className="text-sm leading-6 text-muted-foreground">Desktop-first shell for knowledge work, review flow, and agent interaction.</p>
            <div className="flex flex-wrap items-center gap-2">
              <Badge>Viewport locked</Badge>
              <Badge variant="outline">Hybrid scroll model</Badge>
            </div>
          </div>

          <nav className="space-y-2">{renderNavLink('primary')}</nav>

          <div className="mt-auto space-y-4 px-2 pt-6">
            <div className="rounded-[24px] border border-border/80 bg-panel-muted p-4">
              <div className="text-xs uppercase tracking-[0.22em] text-muted-foreground">Current surface</div>
              <div className="mt-2 text-base font-semibold tracking-tight text-foreground">{currentNavItem.label}</div>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{currentNavItem.description}</p>
            </div>
            <div className="space-y-2 border-t border-border/70 pt-4">{renderNavLink('utility')}</div>
          </div>
        </aside>

        <section className="flex min-w-0 flex-col overflow-hidden rounded-[30px] border border-border/70 bg-card/92 shadow-shell backdrop-blur-xl">
          <header className="flex h-16 items-center justify-between gap-4 border-b border-border/70 px-6">
            <div>
              <div className="text-[11px] uppercase tracking-[0.28em] text-muted-foreground">Workspace</div>
              <div className="mt-1 text-sm font-medium text-foreground">{currentNavItem.label}</div>
            </div>
            <div className="flex items-center gap-2">
              {onOpenCommandPalette ? (
                <Button type="button" variant="secondary" size="sm" onClick={onOpenCommandPalette}>
                  <Search className="h-4 w-4" />
                  Command
                  <kbd className="hidden rounded-full border border-border/70 bg-background/70 px-2 py-0.5 text-[10px] uppercase tracking-[0.2em] text-muted-foreground sm:inline-flex">
                    Ctrl K
                  </kbd>
                </Button>
              ) : null}
              <div className="hidden items-center gap-2 lg:flex">
              <Badge variant="outline">FastAPI + Vite</Badge>
              <Badge variant="muted">Legacy routes preserved</Badge>
              </div>
            </div>
          </header>

          <main className="app-scrollbar flex-1 overflow-y-auto px-6 py-6">{children}</main>
        </section>
      </div>
    </div>
  );
}