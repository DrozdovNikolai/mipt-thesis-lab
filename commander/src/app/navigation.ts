import { PRIVILEGES } from '@/entities/session/privileges'

export const navigation = [
  { label: 'Analytics', to: '/analytics', privileges: [PRIVILEGES.PILOTS_READ], end: true },
  { label: 'Compatibility', to: '/compatibility', privileges: [PRIVILEGES.PILOTS_READ], end: true },
  { label: 'Pilots', to: '/pilots', privileges: [PRIVILEGES.PILOTS_READ], end: false },
  {
    label: 'Training sessions',
    to: '/training-sessions',
    privileges: [PRIVILEGES.PILOTS_READ],
    end: false,
  },
  { label: 'Settings', to: '/settings', privileges: [PRIVILEGES.PILOTS_READ], end: true },
  { label: 'Admin', to: '/admin', privileges: [PRIVILEGES.USERS_READ], end: true },
] as const
