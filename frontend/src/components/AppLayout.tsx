import type { ReactNode } from 'react';
import { navItems, resolveBackendHref } from '../lib/navigation';

type AppLayoutProps = {
  active: string;
  children: ReactNode;
};

export function AppLayout({ active, children }: AppLayoutProps) {
  return (
    <div className="container chat-layout">
      <nav className="nav">
        <span className="brand">Learning Agent</span>
        {navItems.map((item) => (
          <a key={item.href} href={item.migrated ? item.href : resolveBackendHref(item.href)} className={active === item.href ? 'active' : undefined}>
            {item.label}
          </a>
        ))}
      </nav>
      {children}
    </div>
  );
}