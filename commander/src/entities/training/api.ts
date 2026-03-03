import { api } from '@/shared/api/api'
import { endpoints } from '@/shared/api/endpoints'
import type {
  AircraftAirline,
  Airline,
  AirlineGradingScale,
  ReplaceAirlineGradingScalePayload,
  ContentSetSummaryPage,
  Element,
  ElementBlock,
  FolderItem,
  Module,
  ScenarioSummaryPage,
  TaskFolder,
} from './types'
import type { Scenario } from './types'
import type { ScenarioSnapshot } from './scenarioSnapshot'
import type {
  ScenarioRevisionDetail,
  ScenarioRevisionKind,
  ScenarioRevisionListItem,
} from './scenarioRevisions'
import type {
  BehaviouralIndicatorRead,
  CompetenceRead,
  ExerciseRead,
  ScenarioContentCellRead,
  ScenarioContentFolderRead,
  ScenarioContentRequirementElementRead,
  ScenarioContentRequirementRead,
  ScenarioContentSetMatrix,
  ScenarioContentSetRead,
  ScenarioContentSetSubcolumns,
  ScenarioContentSubColumnRead,
  ScenarioContentSetLabelRead,
} from './types.generated'

type ElementCreatePayload = Pick<Element, 'name' | 'severity' | 'defaultDurationMinutes'>
type ElementUpdatePayload = Partial<ElementCreatePayload>
type FolderItemCreatePayload = {
  folderId: number
  itemType: 'ELEMENT' | 'BLOCK'
  elementId?: number | null
  blockId?: number | null
  orderIndex?: number
}
type FolderItemUpdatePayload = Partial<{
  folderId: number | null
  itemType: 'ELEMENT' | 'BLOCK' | null
  elementId: number | null
  blockId: number | null
  orderIndex: number | null
}>

type BlockFolderItemCreatePayload = {
  folderId: number
  blockId: number
  orderIndex?: number
}
type BlockFolderItemUpdatePayload = Partial<{
  folderId: number | null
  blockId: number | null
  orderIndex: number | null
}>
type FolderCreatePayload = {
  name: string
  parentId?: number | null
  colorHex?: string | null
  aircraftId?: number | string | null
  orderIndex?: number | null
}
type FolderUpdatePayload = Partial<FolderCreatePayload>

type ScenarioCreatePayload = Pick<Scenario, 'title'> &
  Partial<
    Pick<
      Scenario,
      'aircraftId' | 'code' | 'engines' | 'comments' | 'status' | 'publishedAt' | 'validUntil'
    >
  > & {
    contentSetId?: number | null
    setLabelId?: number | null
  }
type ScenarioUpdatePayload = Partial<
  Pick<
    Scenario,
    | 'aircraftId'
    | 'code'
    | 'title'
    | 'engines'
    | 'comments'
    | 'status'
    | 'publishedAt'
    | 'validUntil'
  >
>

type CompetenceCreatePayload = {
  code: string
  name: string
  description?: string | null
}

type CompetenceUpdatePayload = Partial<CompetenceCreatePayload>

type BehaviouralIndicatorCreatePayload = {
  code: string
  shortName?: string | null
  name: string
  orderIndex?: number
}

type BehaviouralIndicatorUpdatePayload = Partial<BehaviouralIndicatorCreatePayload>

const isHelperPositiveIndicator = (indicator: BehaviouralIndicatorRead) =>
  indicator.code.trim().toLowerCase() === 'positive'

const filterHelperPositiveIndicators = (indicators: BehaviouralIndicatorRead[]) =>
  indicators.filter((indicator) => !isHelperPositiveIndicator(indicator))

type BlockElementPayload = {
  id?: number | null
  elementId: number
  orderIndex: number
  details?: string | null
  startingHeight?: number | null
  endingHeight?: number | null
  profileType?: 'FLAT' | 'UP' | 'DOWN' | 'LINKED'
}
type BlockCreatePayload = {
  params?: ElementBlockParamPayload | null
  elements?: BlockElementPayload[]
  competenceIds?: number[]
}
type BlockUpdatePayload = Partial<Omit<BlockCreatePayload, 'elements'>> & {
  elements?: BlockElementPayload[] | null
}

type ModuleCreatePayload = {
  scenarioId: number
  orderIndex?: number
  dayStart?: boolean
  durationMinutes?: number | null
  contentSubcolumnId?: number | null
}
type ModuleUpdatePayload = Partial<
  Pick<ModuleCreatePayload, 'orderIndex' | 'dayStart' | 'durationMinutes' | 'contentSubcolumnId'>
>

type ExerciseElementPayload = {
  elementId: number
  orderIndex?: number
  details?: string | null
  startingHeight?: number | null
  endingHeight?: number | null
  profileType?: 'FLAT' | 'UP' | 'DOWN' | 'LINKED'
}
type ExerciseParamPayload = {
  intensity?: string | null
  zfwT?: string | null
  guidance?: string | null
  originalTl?: Record<string, unknown> | null
  destinationTl?: Record<string, unknown> | null
}

type ElementBlockParamPayload = ExerciseParamPayload & {
  durationMinutes?: number | null
  crewMemberNumber?: number | null
}
type ExerciseCreatePayload = {
  moduleId: number
  orderIndex?: number
  durationMinutes?: number | null
  crewMemberNumber?: number | null
  elements?: ExerciseElementPayload[]
  params?: ExerciseParamPayload | null
  competenceIds?: number[]
}
type ExerciseUpdatePayload = Partial<Omit<ExerciseCreatePayload, 'moduleId'>> & {
  moduleId?: number
}

type ScenarioContentSetCreatePayload = {
  aircraftId?: number | string | null
  name: string
  validFrom?: string | null
  validTo?: string | null
}
type ScenarioContentSetUpdatePayload = Partial<ScenarioContentSetCreatePayload>

type ScenarioContentSetLabelCreatePayload = {
  label?: string | null
  orderIndex?: number | null
}
type ScenarioContentSetLabelUpdatePayload = Partial<{
  label: string | null
  orderIndex: number | null
}>

type ScenarioContentFolderCreatePayload = {
  name: string
  parentId?: number | null
  orderIndex?: number | null
}
type ScenarioContentFolderUpdatePayload = Partial<ScenarioContentFolderCreatePayload>

type ScenarioContentRequirementCreatePayload = {
  folderId: number
  topicName: string
  orderIndex?: number | null
}
type ScenarioContentRequirementUpdatePayload = Partial<{
  folderId: number | null
  topicName: string | null
  orderIndex: number | null
}>

type ScenarioContentRequirementElementCreatePayload = {
  elementId: number
  orderIndex?: number | null
}
type ScenarioContentRequirementElementUpdatePayload = Partial<{
  orderIndex: number | null
}>

type ScenarioContentSubColumnCreatePayload = {
  name: string
  orderIndex?: number | null
}
type ScenarioContentSubColumnUpdatePayload = Partial<ScenarioContentSubColumnCreatePayload>

type ScenarioContentCellUpsertPayload = {
  requirementId: number
  subcolumnId: number
  setLabelId: number
  value: boolean
}

type ScenarioRevisionCreatePayload = {
  kind?: ScenarioRevisionKind
  label?: string | null
  clientEntryId?: string | null
  clientCreatedAtMs?: number | null
  snapshot: ScenarioSnapshot
}

type ScenarioRevisionBatchItem = {
  clientEntryId: string
  clientCreatedAtMs: number
  kind?: ScenarioRevisionKind
  label?: string | null
  snapshot: ScenarioSnapshot
}

type ScenarioRevisionBatchCreatePayload = {
  items: ScenarioRevisionBatchItem[]
}

type ScenarioSnapshotApplyPayload = {
  snapshot: ScenarioSnapshot
}

type ScenarioSnapshotApplyOptions = {
  allowMissingIds?: boolean
  expectedVersion: number
  clientSessionId: string
}

type ScenarioSnapshotApplyResponse = {
  scenarioId: number
  contentVersion: number
  snapshot: ScenarioSnapshot
  moduleIdMap: Record<string, number>
  exerciseIdMap: Record<string, number>
}

export type ScenarioEditLockOwner = {
  id: number
  login: string
  firstName: string | null
  lastName: string | null
}

export type ScenarioEditLockStatus = {
  scenarioId: number
  isLocked: boolean
  expiresAt: string | null
  owner: ScenarioEditLockOwner | null
  isOwner: boolean
}

export type ScenarioPublishValidationMissingElement = {
  elementId: number
  name: string
}

export type ScenarioPublishValidationMissingTopic = {
  requirementId: number
  topicName: string
  elements: ScenarioPublishValidationMissingElement[]
}

export type ScenarioPublishValidationGroup = {
  contentSetId: number
  contentSetName: string
  setLabelId: number
  subcolumnId: number
  subcolumnName: string
  missingTopics: ScenarioPublishValidationMissingTopic[]
}

export type ScenarioPublishValidationResponse = {
  ok: boolean
  missing: ScenarioPublishValidationGroup[]
}

type ScenarioEditLockAcquirePayload = {
  clientSessionId: string
  force?: boolean
}

export const trainingApi = {
  airlines: {
    list: () => api.get<Airline[]>(`${endpoints.training.airlines}`),
    create: (payload: Pick<Airline, 'code' | 'name' | 'active' | 'usersStoredInLocalDb'>) =>
      api.post<Airline>(`${endpoints.training.airlines}`, payload),
    update: (
      airlineId: number,
      payload: Partial<Pick<Airline, 'code' | 'name' | 'active' | 'usersStoredInLocalDb'>>,
    ) => api.put<Airline>(`${endpoints.training.airlines}/${airlineId}`, payload),
    delete: (airlineId: number) => api.delete<void>(`${endpoints.training.airlines}/${airlineId}`),
    gradingScale: {
      get: (airlineId: number) =>
        api.get<AirlineGradingScale>(`${endpoints.training.airlines}/${airlineId}/grading-scale`),
      replace: (airlineId: number, payload: ReplaceAirlineGradingScalePayload) =>
        api.put<AirlineGradingScale>(
          `${endpoints.training.airlines}/${airlineId}/grading-scale`,
          payload,
        ),
    },
  },
  aircraft: {
    list: (airlineId?: number | null) =>
      api.get<AircraftAirline[]>(`${endpoints.training.root}/aircraft`, {
        query: { airlineId: airlineId ?? undefined },
      }),
    create: (payload: Pick<AircraftAirline, 'airlineId' | 'code' | 'name' | 'active'>) =>
      api.post<AircraftAirline>(`${endpoints.training.root}/aircraft`, payload),
    update: (
      aircraftId: number,
      payload: Partial<Pick<AircraftAirline, 'code' | 'name' | 'active'>>,
    ) => api.put<AircraftAirline>(`${endpoints.training.root}/aircraft/${aircraftId}`, payload),
    delete: (aircraftId: number) =>
      api.delete<void>(`${endpoints.training.root}/aircraft/${aircraftId}`),
  },
  scenarios: {
    list: () => api.get<Scenario[]>(`${endpoints.training.scenarios}`),
    summary: (params?: {
      aircraftId?: number | string | null
      q?: string | null
      status?: string | null
      sort?: string | null
      limit?: number | null
      offset?: number | null
    }) =>
      api.get<ScenarioSummaryPage>(`${endpoints.training.scenarios}/summary`, {
        query: {
          aircraftId: params?.aircraftId ?? undefined,
          q: params?.q ?? undefined,
          status: params?.status ?? undefined,
          sort: params?.sort ?? undefined,
          limit: params?.limit ?? undefined,
          offset: params?.offset ?? undefined,
        },
      }),
    get: (scenarioId: number) => api.get<Scenario>(`${endpoints.training.scenarios}/${scenarioId}`),
    create: (payload: ScenarioCreatePayload) =>
      api.post<Scenario>(`${endpoints.training.scenarios}`, payload),
    update: (scenarioId: number, payload: ScenarioUpdatePayload) =>
      api.put<Scenario>(`${endpoints.training.scenarios}/${scenarioId}`, payload),
    delete: (scenarioId: number) =>
      api.delete<void>(`${endpoints.training.scenarios}/${scenarioId}`),
    duplicate: (
      scenarioId: number,
      payload: { title?: string | null; contentSetId?: number | null; setLabelId?: number | null },
      clientSessionId: string,
    ) =>
      api.post<Scenario>(`${endpoints.training.scenarios}/${scenarioId}/duplicate`, payload, {
        headers: { 'X-Client-Session-Id': clientSessionId },
      }),
    applySnapshot: (
      scenarioId: number,
      payload: ScenarioSnapshotApplyPayload,
      options: ScenarioSnapshotApplyOptions,
    ) =>
      api.put<ScenarioSnapshotApplyResponse>(
        `${endpoints.training.scenarios}/${scenarioId}/snapshot`,
        payload,
        {
          query: {
            allowMissingIds: options.allowMissingIds ? true : undefined,
            expectedVersion: options.expectedVersion,
          },
          headers: { 'X-Client-Session-Id': options.clientSessionId },
        },
      ),
    contentSetSubcolumns: (scenarioId: number) =>
      api.get<ScenarioContentSetSubcolumns[]>(
        `${endpoints.training.scenarios}/${scenarioId}/content-set-subcolumns`,
      ),
    publishValidation: (scenarioId: number) =>
      api.get<ScenarioPublishValidationResponse>(
        `${endpoints.training.scenarios}/${scenarioId}/publish-validation`,
      ),
    locks: {
      get: (scenarioId: number, clientSessionId?: string) =>
        api.get<ScenarioEditLockStatus>(`${endpoints.training.scenarios}/${scenarioId}/lock`, {
          headers: clientSessionId ? { 'X-Client-Session-Id': clientSessionId } : undefined,
        }),
      acquire: (scenarioId: number, payload: ScenarioEditLockAcquirePayload) =>
        api.post<ScenarioEditLockStatus>(
          `${endpoints.training.scenarios}/${scenarioId}/lock`,
          payload,
        ),
      release: (scenarioId: number, clientSessionId: string) =>
        api.delete<void>(`${endpoints.training.scenarios}/${scenarioId}/lock`, {
          headers: { 'X-Client-Session-Id': clientSessionId },
        }),
    },
  },
  scenarioRevisions: {
    list: (scenarioId: number, limit?: number) =>
      api.get<ScenarioRevisionListItem[]>(
        `${endpoints.training.scenarios}/${scenarioId}/revisions`,
        {
          query: { limit: limit ?? undefined },
        },
      ),
    snapshots: (scenarioId: number, limit?: number) =>
      api.get<ScenarioRevisionDetail[]>(
        `${endpoints.training.scenarios}/${scenarioId}/revisions/snapshots`,
        {
          query: { limit: limit ?? undefined },
        },
      ),
    get: (scenarioId: number, revisionId: number) =>
      api.get<ScenarioRevisionDetail>(
        `${endpoints.training.scenarios}/${scenarioId}/revisions/${revisionId}`,
      ),
    create: (scenarioId: number, payload: ScenarioRevisionCreatePayload) =>
      api.post<ScenarioRevisionListItem>(
        `${endpoints.training.scenarios}/${scenarioId}/revisions`,
        payload,
      ),
    batchCreate: (scenarioId: number, payload: ScenarioRevisionBatchCreatePayload) =>
      api.post<ScenarioRevisionListItem[]>(
        `${endpoints.training.scenarios}/${scenarioId}/revisions/batch`,
        payload,
      ),
  },
  competences: {
    list: () => api.get<CompetenceRead[]>(`${endpoints.training.competences}`),
    create: (payload: CompetenceCreatePayload) =>
      api.post<CompetenceRead>(`${endpoints.training.competences}`, payload),
    update: (competenceId: number, payload: CompetenceUpdatePayload) =>
      api.put<CompetenceRead>(`${endpoints.training.competences}/${competenceId}`, payload),
    delete: (competenceId: number) =>
      api.delete<void>(`${endpoints.training.competences}/${competenceId}`),
    reorder: (competenceIds: number[]) =>
      api.put<void>(`${endpoints.training.competences}/order`, { competenceIds: competenceIds }),
    behaviouralIndicators: {
      list: (competenceId: number) =>
        api
          .get<BehaviouralIndicatorRead[]>(
            `${endpoints.training.competences}/${competenceId}/behavioural-indicators`,
          )
          .then(filterHelperPositiveIndicators),
      create: (competenceId: number, payload: BehaviouralIndicatorCreatePayload) =>
        api.post<BehaviouralIndicatorRead>(
          `${endpoints.training.competences}/${competenceId}/behavioural-indicators`,
          payload,
        ),
      update: (
        competenceId: number,
        indicatorId: number,
        payload: BehaviouralIndicatorUpdatePayload,
      ) =>
        api.put<BehaviouralIndicatorRead>(
          `${endpoints.training.competences}/${competenceId}/behavioural-indicators/${indicatorId}`,
          payload,
        ),
      delete: (competenceId: number, indicatorId: number) =>
        api.delete<void>(
          `${endpoints.training.competences}/${competenceId}/behavioural-indicators/${indicatorId}`,
        ),
    },
  },
  modules: {
    create: (payload: ModuleCreatePayload) =>
      api.post<Module>(`${endpoints.training.modules}`, payload),
    update: (moduleId: number, payload: ModuleUpdatePayload) =>
      api.put<Module>(`${endpoints.training.modules}/${moduleId}`, payload),
    delete: (moduleId: number) => api.delete<void>(`${endpoints.training.modules}/${moduleId}`),
  },
  exercises: {
    create: (payload: ExerciseCreatePayload) =>
      api.post<ExerciseRead>(`${endpoints.training.exercises}`, payload),
    update: (exerciseId: number, payload: ExerciseUpdatePayload) =>
      api.put<ExerciseRead>(`${endpoints.training.exercises}/${exerciseId}`, payload),
    delete: (exerciseId: number) =>
      api.delete<void>(`${endpoints.training.exercises}/${exerciseId}`),
  },
  folders: {
    list: (aircraftId?: number | string | null) =>
      api.get<TaskFolder[]>(`${endpoints.training.folders}`, {
        query: { aircraftId: aircraftId ?? undefined },
      }),
    create: (payload: FolderCreatePayload) =>
      api.post<TaskFolder>(`${endpoints.training.folders}`, payload),
    update: (folderId: number, payload: FolderUpdatePayload) =>
      api.put<TaskFolder>(`${endpoints.training.folders}/${folderId}`, payload),
    delete: (folderId: number) => api.delete<void>(`${endpoints.training.folders}/${folderId}`),
  },
  folderItems: {
    list: (folderId: number) =>
      api.get<FolderItem[]>(`${endpoints.training.folderItems}?folderId=${folderId}`),
    listByFolders: async (folderIds: number[]) => {
      const results = await Promise.all(
        folderIds.map((id) =>
          api.get<FolderItem[]>(`${endpoints.training.folderItems}?folderId=${id}`),
        ),
      )
      return results.flat()
    },
    create: (payload: FolderItemCreatePayload) =>
      api.post<FolderItem>(`${endpoints.training.folderItems}`, payload),
    update: (itemId: number, payload: FolderItemUpdatePayload) =>
      api.put<FolderItem>(`${endpoints.training.folderItems}/${itemId}`, payload),
    delete: (itemId: number) => api.delete<void>(`${endpoints.training.folderItems}/${itemId}`),
  },
  blockFolders: {
    list: (aircraftId?: number | string | null) =>
      api.get<TaskFolder[]>(`${endpoints.training.blockFolders}`, {
        query: { aircraftId: aircraftId ?? undefined },
      }),
    create: (payload: FolderCreatePayload) =>
      api.post<TaskFolder>(`${endpoints.training.blockFolders}`, payload),
    update: (folderId: number, payload: FolderUpdatePayload) =>
      api.put<TaskFolder>(`${endpoints.training.blockFolders}/${folderId}`, payload),
    delete: (folderId: number) =>
      api.delete<void>(`${endpoints.training.blockFolders}/${folderId}`),
  },
  blockFolderItems: {
    list: (folderId: number) =>
      api.get<FolderItem[]>(`${endpoints.training.blockFolderItems}?folderId=${folderId}`),
    listByFolders: async (folderIds: number[]) => {
      const results = await Promise.all(
        folderIds.map((id) =>
          api.get<FolderItem[]>(`${endpoints.training.blockFolderItems}?folderId=${id}`),
        ),
      )
      return results.flat()
    },
    create: (payload: BlockFolderItemCreatePayload) =>
      api.post<FolderItem>(`${endpoints.training.blockFolderItems}`, payload),
    update: (itemId: number, payload: BlockFolderItemUpdatePayload) =>
      api.put<FolderItem>(`${endpoints.training.blockFolderItems}/${itemId}`, payload),
    delete: (itemId: number) =>
      api.delete<void>(`${endpoints.training.blockFolderItems}/${itemId}`),
  },
  elements: {
    list: () => api.get<Element[]>(`${endpoints.training.elements}`),
    create: (payload: ElementCreatePayload) =>
      api.post<Element>(`${endpoints.training.elements}`, payload),
    update: (elementId: number, payload: ElementUpdatePayload) =>
      api.put<Element>(`${endpoints.training.elements}/${elementId}`, payload),
    delete: (elementId: number) => api.delete<void>(`${endpoints.training.elements}/${elementId}`),
  },
  blocks: {
    list: () => api.get<ElementBlock[]>(`${endpoints.training.blocks}`),
    create: (payload: BlockCreatePayload) =>
      api.post<ElementBlock>(`${endpoints.training.blocks}`, payload),
    update: (blockId: number, payload: BlockUpdatePayload) =>
      api.put<ElementBlock>(`${endpoints.training.blocks}/${blockId}`, payload),
    delete: (blockId: number) => api.delete<void>(`${endpoints.training.blocks}/${blockId}`),
  },
  contentSets: {
    list: (aircraftId?: number | string | null) =>
      api.get<ScenarioContentSetRead[]>(`${endpoints.training.contentSets}`, {
        query: { aircraftId: aircraftId ?? undefined },
      }),
    summary: (params?: {
      aircraftId?: number | string | null
      q?: string | null
      sort?: string | null
      limit?: number | null
      offset?: number | null
    }) =>
      api.get<ContentSetSummaryPage>(`${endpoints.training.contentSets}/summary`, {
        query: {
          aircraftId: params?.aircraftId ?? undefined,
          q: params?.q ?? undefined,
          sort: params?.sort ?? undefined,
          limit: params?.limit ?? undefined,
          offset: params?.offset ?? undefined,
        },
      }),
    create: (payload: ScenarioContentSetCreatePayload) =>
      api.post<ScenarioContentSetRead>(`${endpoints.training.contentSets}`, payload),
    update: (contentSetId: number, payload: ScenarioContentSetUpdatePayload) =>
      api.put<ScenarioContentSetRead>(`${endpoints.training.contentSets}/${contentSetId}`, payload),
    delete: (contentSetId: number) =>
      api.delete<void>(`${endpoints.training.contentSets}/${contentSetId}`),
    duplicate: (
      contentSetId: number,
      payload?: { name?: string | null; aircraftId?: number | string | null },
    ) =>
      api.post<ScenarioContentSetRead>(
        `${endpoints.training.contentSets}/${contentSetId}/duplicate`,
        payload ?? {},
      ),
    matrix: (contentSetId: number) =>
      api.get<ScenarioContentSetMatrix>(`${endpoints.training.contentSets}/${contentSetId}`),
    labels: {
      add: (contentSetId: number, payload: ScenarioContentSetLabelCreatePayload) =>
        api.post<ScenarioContentSetLabelRead>(
          `${endpoints.training.contentSets}/${contentSetId}/labels`,
          payload,
        ),
      update: (
        contentSetId: number,
        labelId: number,
        payload: ScenarioContentSetLabelUpdatePayload,
      ) =>
        api.put<ScenarioContentSetLabelRead>(
          `${endpoints.training.contentSets}/${contentSetId}/labels/${labelId}`,
          payload,
        ),
      delete: (contentSetId: number, labelId: number) =>
        api.delete<void>(`${endpoints.training.contentSets}/${contentSetId}/labels/${labelId}`),
    },
    subcolumns: {
      create: (contentSetId: number, payload: ScenarioContentSubColumnCreatePayload) =>
        api.post<ScenarioContentSubColumnRead>(
          `${endpoints.training.contentSets}/${contentSetId}/subcolumns`,
          payload,
        ),
      update: (
        contentSetId: number,
        subcolumnId: number,
        payload: ScenarioContentSubColumnUpdatePayload,
      ) =>
        api.put<ScenarioContentSubColumnRead>(
          `${endpoints.training.contentSets}/${contentSetId}/subcolumns/${subcolumnId}`,
          payload,
        ),
      delete: (contentSetId: number, subcolumnId: number) =>
        api.delete<void>(
          `${endpoints.training.contentSets}/${contentSetId}/subcolumns/${subcolumnId}`,
        ),
    },
    folders: {
      create: (contentSetId: number, payload: ScenarioContentFolderCreatePayload) =>
        api.post<ScenarioContentFolderRead>(
          `${endpoints.training.contentSets}/${contentSetId}/folders`,
          payload,
        ),
      update: (
        contentSetId: number,
        folderId: number,
        payload: ScenarioContentFolderUpdatePayload,
      ) =>
        api.put<ScenarioContentFolderRead>(
          `${endpoints.training.contentSets}/${contentSetId}/folders/${folderId}`,
          payload,
        ),
      delete: (contentSetId: number, folderId: number) =>
        api.delete<void>(`${endpoints.training.contentSets}/${contentSetId}/folders/${folderId}`),
    },
    requirements: {
      create: (contentSetId: number, payload: ScenarioContentRequirementCreatePayload) =>
        api.post<ScenarioContentRequirementRead>(
          `${endpoints.training.contentSets}/${contentSetId}/requirements`,
          payload,
        ),
      update: (
        contentSetId: number,
        requirementId: number,
        payload: ScenarioContentRequirementUpdatePayload,
      ) =>
        api.put<ScenarioContentRequirementRead>(
          `${endpoints.training.contentSets}/${contentSetId}/requirements/${requirementId}`,
          payload,
        ),
      delete: (contentSetId: number, requirementId: number) =>
        api.delete<void>(
          `${endpoints.training.contentSets}/${contentSetId}/requirements/${requirementId}`,
        ),
      elements: {
        create: (
          contentSetId: number,
          requirementId: number,
          payload: ScenarioContentRequirementElementCreatePayload,
        ) =>
          api.post<ScenarioContentRequirementElementRead>(
            `${endpoints.training.contentSets}/${contentSetId}/requirements/${requirementId}/elements`,
            payload,
          ),
        update: (
          contentSetId: number,
          requirementId: number,
          requirementElementId: number,
          payload: ScenarioContentRequirementElementUpdatePayload,
        ) =>
          api.put<ScenarioContentRequirementElementRead>(
            `${endpoints.training.contentSets}/${contentSetId}/requirements/${requirementId}/elements/${requirementElementId}`,
            payload,
          ),
        delete: (contentSetId: number, requirementId: number, requirementElementId: number) =>
          api.delete<void>(
            `${endpoints.training.contentSets}/${contentSetId}/requirements/${requirementId}/elements/${requirementElementId}`,
          ),
      },
    },
    cells: {
      upsert: (contentSetId: number, payload: ScenarioContentCellUpsertPayload) =>
        api.put<ScenarioContentCellRead>(
          `${endpoints.training.contentSets}/${contentSetId}/cells`,
          payload,
        ),
      deleteByLabel: (
        contentSetId: number,
        requirementId: number,
        subcolumnId: number,
        setLabelId: number,
      ) =>
        api.delete<void>(
          `${endpoints.training.contentSets}/${contentSetId}/cells/by-label/${requirementId}/${subcolumnId}/${setLabelId}`,
        ),
    },
  },
}
