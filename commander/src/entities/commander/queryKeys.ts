export type SessionScope = readonly [userId: string | null, airlineId: number | null]

export const commanderKeys = {
  root: (scope: SessionScope) => ['commander', ...scope] as const,
  aircraft: (scope: SessionScope) => [...commanderKeys.root(scope), 'aircraft'] as const,
  pilots: (scope: SessionScope, filters: object) =>
    [...commanderKeys.root(scope), 'pilots', filters] as const,
  flightTypes: (scope: SessionScope) => [...commanderKeys.root(scope), 'flight-types'] as const,
  competences: (scope: SessionScope) => [...commanderKeys.root(scope), 'competences'] as const,
  compatibility: (scope: SessionScope) =>
    [...commanderKeys.root(scope), 'pilot-compatibility'] as const,
}
