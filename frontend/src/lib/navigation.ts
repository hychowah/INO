const DEV_SERVER_PORT = '5173';
const BACKEND_PORT = '8080';

type LocationLike = Pick<Location, 'protocol' | 'hostname' | 'port'>;

export function resolveBackendHref(path: string, locationLike: LocationLike = window.location) {
  if (locationLike.port !== DEV_SERVER_PORT) {
    return path;
  }
  return `${locationLike.protocol}//${locationLike.hostname}:${BACKEND_PORT}${path}`;
}

export const navItems = [
  { label: 'Dashboard', href: '/' },
  { label: 'Chat', href: '/chat' },
  { label: 'Topics', href: '/topics' },
  { label: 'Concepts', href: '/concepts' },
  { label: 'Graph', href: '/graph' },
  { label: 'Reviews', href: '/reviews' },
  { label: 'Forecast', href: '/forecast' },
  { label: 'Activity', href: '/actions' },
] as const;