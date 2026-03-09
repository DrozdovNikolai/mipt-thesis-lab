import { api } from '@/shared/api/api'
import { endpoints } from '@/shared/api/endpoints'
import type { SessionUser, Role, Privilege } from '../session/types'
import type { AirlinePosition } from './types'

const withTrailingSlash = (path: string) => (path.endsWith('/') ? path : `${path}/`)
const usersCollection = withTrailingSlash(endpoints.users.root)
const rolesCollection = withTrailingSlash(endpoints.users.roles)
const privilegesCollection = withTrailingSlash(endpoints.users.privileges)

export type CreateUserPayload = {
  login: string
  email: string
  password: string
  roles: string[]
  airlineId?: number | null
  aircraftIds?: number[]
  firstName?: string | null
  lastName?: string | null
  position?: string | null
  licenseNumber?: string | null
  phone?: string | null
}

export type UpdateUserPayload = Partial<{
  login: string
  email: string
  password: string
  airlineId: number | null
  aircraftIds: number[]
  firstName: string | null
  lastName: string | null
  position: string | null
  licenseNumber: string | null
  phone: string | null
}>

export type UpdateUserRolesPayload = {
  roleIds: string[]
}

export const usersApi = {
  list: () => api.get<SessionUser[]>(usersCollection),
  create: (payload: CreateUserPayload) =>
    api.post<SessionUser, CreateUserPayload>(usersCollection, payload),
  update: (userId: string, payload: UpdateUserPayload) =>
    api.put<SessionUser, UpdateUserPayload>(`${endpoints.users.root}/${userId}`, payload),
  updateRoles: (userId: string, payload: UpdateUserRolesPayload) =>
    api.put<SessionUser, UpdateUserRolesPayload>(
      `${endpoints.users.root}/${userId}/roles`,
      payload,
    ),
  uploadPhoto: async (userId: string, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post<{ photoUrl: string }, FormData>(
      `${endpoints.users.root}/${userId}/photo/upload`,
      formData,
    )
  },
  delete: (userId: string) => api.delete<void>(`${endpoints.users.root}/${userId}`),
}

export type RoleCreatePayload = {
  name: string
  description?: string | null
  privileges: string[]
}

export type RoleUpdatePayload = Partial<{
  name: string
  description: string | null
  privileges: string[]
}>

export const rolesApi = {
  list: () => api.get<Role[]>(rolesCollection),
  create: (payload: RoleCreatePayload) =>
    api.post<Role, RoleCreatePayload>(rolesCollection, payload),
  update: (roleId: string, payload: RoleUpdatePayload) =>
    api.put<Role, RoleUpdatePayload>(`${endpoints.users.roles}/${roleId}`, payload),
  delete: (roleId: string) => api.delete<void>(`${endpoints.users.roles}/${roleId}`),
}

export type PrivilegeCreatePayload = {
  name: string
  description?: string | null
}

export type PrivilegeUpdatePayload = Partial<{
  name: string
  description: string | null
}>

export const privilegesApi = {
  list: () => api.get<Privilege[]>(privilegesCollection),
  create: (payload: PrivilegeCreatePayload) =>
    api.post<Privilege, PrivilegeCreatePayload>(privilegesCollection, payload),
  update: (privilegeId: string, payload: PrivilegeUpdatePayload) =>
    api.put<Privilege, PrivilegeUpdatePayload>(
      `${endpoints.users.privileges}/${privilegeId}`,
      payload,
    ),
  delete: (privilegeId: string) => api.delete<void>(`${endpoints.users.privileges}/${privilegeId}`),
}

export const positionsApi = {
  list: () => api.get<AirlinePosition[]>(endpoints.users.positions),
}
