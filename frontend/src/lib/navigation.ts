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
  { label: 'Dashboard', href: '/', migrated: true },
  { label: 'Chat', href: '/chat', migrated: true },
  { label: 'Topics', href: '/topics', migrated: true },
  { label: 'Concepts', href: '/concepts', migrated: true },
  { label: 'Graph', href: '/graph', migrated: true },
  { label: 'Reviews', href: '/reviews', migrated: true },
  { label: 'Forecast', href: '/forecast', migrated: true },
  { label: 'Activity', href: '/actions', migrated: true },
] as const;