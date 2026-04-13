import type { LucideIcon } from 'lucide-react';
import { Activity, BookMarked, LayoutDashboard, MessageSquareMore, TrendingUp } from 'lucide-react';

const DEV_SERVER_PORT = '5173';
const BACKEND_PORT = '8080';

type LocationLike = Pick<Location, 'protocol' | 'hostname' | 'port'>;

export type AppNavItem = {
  label: string;
  href: string;
  icon: LucideIcon;
  description: string;
  matches: string[];
};

export function resolveBackendHref(path: string, locationLike: LocationLike = window.location) {
  if (locationLike.port !== DEV_SERVER_PORT) {
    return path;
  }
  return `${locationLike.protocol}//${locationLike.hostname}:${BACKEND_PORT}${path}`;
}

export function resolvePreferredNavHref(activePath: string, itemHref: string) {
  if (itemHref === '/knowledge') {
    if (activePath === '/concepts' || activePath === '/knowledge/concepts') {
      return '/knowledge/concepts';
    }
    if (activePath === '/graph' || activePath === '/knowledge/graph') {
      return '/knowledge/graph';
    }
    return '/knowledge';
  }

  if (itemHref === '/progress' && (activePath === '/forecast' || activePath === '/progress/forecast')) {
    return '/progress/forecast';
  }

  return itemHref;
}

export const primaryNavItems: readonly AppNavItem[] = [
  {
    label: 'Dashboard',
    href: '/',
    icon: LayoutDashboard,
    description: 'Overview, due work, and live system health.',
    matches: ['/'],
  },
  {
    label: 'Chat',
    href: '/chat',
    icon: MessageSquareMore,
    description: 'Direct agent interaction with command actions and notes.',
    matches: ['/chat'],
  },
  {
    label: 'Knowledge',
    href: '/knowledge',
    icon: BookMarked,
    description: 'Topics, concepts, and graph exploration.',
    matches: ['/knowledge', '/topics', '/topic', '/concepts', '/concept', '/graph'],
  },
  {
    label: 'Progress',
    href: '/progress',
    icon: TrendingUp,
    description: 'Review history, forecast load, and performance trends.',
    matches: ['/reviews', '/forecast', '/progress'],
  },
] as const;

export const utilityNavItems: readonly AppNavItem[] = [
  {
    label: 'Activity',
    href: '/actions',
    icon: Activity,
    description: 'Operational log with filters and event detail.',
    matches: ['/actions'],
  },
] as const;

export function isNavItemActive(activePath: string, item: AppNavItem) {
  if (item.href === '/') {
    return activePath === '/';
  }

  return item.matches.some((match) => activePath === match || activePath.startsWith(`${match}/`));
}

export function resolveActiveNavItem(activePath: string) {
  return [...primaryNavItems, ...utilityNavItems].find((item) => isNavItemActive(activePath, item)) ?? primaryNavItems[0];
}