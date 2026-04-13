import { useEffect, useMemo, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { ActivityDrawer } from './ActivityDrawer';
import { AppLayout } from './AppLayout';
import { CommandPalette, type CommandPaletteItem } from './CommandPalette';
import { primaryNavItems, resolvePreferredNavHref, utilityNavItems } from '@/lib/navigation';

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const searchParams = new URLSearchParams(location.search);
  const activityDrawerOpen = location.pathname !== '/actions' && searchParams.get('activity') === '1';
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);

  function setActivityDrawerOpen(open: boolean) {
    const nextParams = new URLSearchParams(location.search);
    if (open) {
      nextParams.set('activity', '1');
    } else {
      nextParams.delete('activity');
    }

    const nextSearch = nextParams.toString();
    navigate(
      {
        pathname: location.pathname,
        search: nextSearch ? `?${nextSearch}` : '',
      },
      { replace: true }
    );
  }

  const commandItems = useMemo<CommandPaletteItem[]>(() => {
    const navigationItems = primaryNavItems.map((item) => ({
      id: item.href,
      label: item.label,
      description: item.description,
      icon: item.icon,
      keywords: item.matches,
      onSelect: () => navigate(resolvePreferredNavHref(location.pathname, item.href)),
    }));

    const activityItem = utilityNavItems[0];
    return navigationItems.concat({
      id: activityItem.href,
      label: activityItem.label,
      description: activityItem.description,
      icon: activityItem.icon,
      keywords: activityItem.matches,
      onSelect: () => {
        if (location.pathname === '/actions') {
          navigate('/actions');
          return;
        }
        setActivityDrawerOpen(true);
      },
    });
  }, [location.pathname, navigate]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'k') {
        return;
      }

      const target = event.target as HTMLElement | null;
      if (target) {
        const tagName = target.tagName.toLowerCase();
        if (tagName === 'input' || tagName === 'textarea' || tagName === 'select' || target.isContentEditable) {
          return;
        }
      }

      event.preventDefault();
      setCommandPaletteOpen((current) => !current);
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <>
      <AppLayout
        active={location.pathname}
        activityDrawerOpen={activityDrawerOpen}
        onOpenActivityDrawer={location.pathname === '/actions' ? undefined : () => setActivityDrawerOpen(true)}
        onOpenCommandPalette={() => setCommandPaletteOpen(true)}
      >
        <Outlet />
      </AppLayout>
      <ActivityDrawer open={activityDrawerOpen} onOpenChange={setActivityDrawerOpen} />
      <CommandPalette open={commandPaletteOpen} onOpenChange={setCommandPaletteOpen} items={commandItems} />
    </>
  );
}