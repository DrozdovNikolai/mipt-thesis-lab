import { inject, type InjectionKey, type Ref } from 'vue'
import type { CommanderPilotProfile } from '@/entities/commander/types'
export const pilotProfileKey: InjectionKey<Readonly<Ref<CommanderPilotProfile | undefined>>> =
  Symbol('pilot-profile')
export function usePilotProfile() {
  const pilot = inject(pilotProfileKey)
  if (!pilot) throw new Error('Pilot profile context is missing.')
  return pilot
}
