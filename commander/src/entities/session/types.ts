export type TokenPair = {
  tokenType: string
  accessToken: string
  refreshToken: string
}

export type Privilege = {
  id: string
  name: string
  description: string | null
  createdAt: string
}

export type Role = {
  id: string
  name: string
  description: string | null
  privileges: Privilege[]
  createdAt: string
}

export type SessionUser = {
  id: string
  login: string
  email: string
  isActive: boolean
  mustChangePassword: boolean
  createdAt: string
  firstName: string | null
  lastName: string | null
  position: string | null
  licenseNumber: string | null
  phone: string | null
  photoUrl: string | null
  signatureUrl: string | null
  airlineId: number | null
  roles: Role[]
  privileges: string[]
  aircraftIds: number[]
  aircraftCodes: string[]
  rating?: string | null
}

export type UserRecurrentCompliance = {
  userId: string
  complianceId: number | null
}
