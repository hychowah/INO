import type { ReactNode } from 'react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { Link, useInRouterContext } from 'react-router-dom';
import { navItems, resolveBackendHref } from '@/lib/navigation';

type AppLayoutProps = {
  active: string;
  children: ReactNode;
};

export function AppLayout({ active, children }: AppLayoutProps) {
  const inRouterContext = useInRouterContext();

  return (
    <div className="min-h-screen bg-slate-950 text-slate-50">
      <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col px-4 pb-8 pt-6 sm:px-6 lg:px-8">
        <header className="mb-6 rounded-[28px] border border-white/10 bg-slate-900/80 px-5 py-5 shadow-[0_30px_80px_rgba(2,6,23,0.55)] backdrop-blur-xl sm:px-6">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge>React Migration</Badge>
                <Badge variant="outline">FastAPI + Vite</Badge>
              </div>
              <div>
                <div className="text-xs uppercase tracking-[0.32em] text-slate-400">Learning Agent</div>
                <h1 className="mt-2 text-2xl font-semibold tracking-tight text-white sm:text-3xl">Knowledge operations, moving into one coherent frontend.</h1>
              </div>
            </div>

            <nav className="flex flex-wrap gap-2 lg:max-w-3xl lg:justify-end">
              {navItems.map((item) => {
                const className = cn(
                  'inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm font-medium transition-colors',
                  active === item.href
                    ? 'border-sky-400/40 bg-sky-400/15 text-sky-100'
                    : 'border-white/10 bg-white/5 text-slate-300 hover:border-white/20 hover:bg-white/10 hover:text-white'
                );

                if (inRouterContext) {
                  return (
                    <Link key={item.href} to={item.href} className={className}>
                      {item.label}
                    </Link>
                  );
                }

                return (
                  <a key={item.href} href={resolveBackendHref(item.href)} className={className}>
                    {item.label}
                  </a>
                );
              })}
            </nav>
          </div>
        </header>

        <main className="flex-1">{children}</main>
      </div>
    </div>
  );
}