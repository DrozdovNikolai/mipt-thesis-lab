export const PRIVILEGES = {
  PILOTS_READ: 'pilots:read',
  PILOTS_WRITE: 'pilots:write',
  USERS_READ: 'users:read',
  USERS_WRITE: 'users:write',
  TRAINING_READ: 'training:read',
  TRAINING_WRITE: 'training:write',
} as const

export type PrivilegeCode = (typeof PRIVILEGES)[keyof typeof PRIVILEGES]
