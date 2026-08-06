import { useCallback, useRef, useState } from 'react';
import { View, useWindowDimensions } from 'react-native';
import type { Client } from '../api/client';
import { exerciseName, type Catalog, type Exercise, type Pilot, type Scenario, type Training } from '../api/models';
import { catalog, createTraining, creationId, plan } from '../api/training';
import { useAction, useLoad } from '../hooks';
import { Action, Copy, Failure, Loading, Page, Panel, Title } from '../ui';
import { CrewPicker } from './CrewPicker';

export interface Workspace {
  scenario: Scenario;
  pilots: [Pilot, Pilot];
  training: Training;
  catalog: Catalog;
}

function Plan({ exercises }: { exercises: Exercise[] }) {
  return <Panel><Title small>План тренировки</Title>{exercises.length ? exercises.map((exercise, i) =>
    <Copy key={exercise.id}>{i + 1}. {exerciseName(exercise)}</Copy>) : <Copy muted>В сценарий пока не добавлены упражнения</Copy>}</Panel>;
}

async function preparation(client: Client, scenario: Scenario) {
  const [exercises, competencies] = await Promise.all([plan(client, scenario.scenarioDayModuleId), catalog(client)]);
  return { exercises, competencies };
}

function useCreationIntent() {
  const previous = useRef({ selection: '', id: '' });
  return (day: number, a: number, b: number) => {
    const selection = [day, a, b].join('/');
    if (previous.current.selection !== selection) previous.current = { selection, id: creationId() };
    return previous.current.id;
  };
}

export function Setup({ client, scenario, back, start }: {
  client: Client; scenario: Scenario; back: () => void; start: (workspace: Workspace) => void;
}) {
  const [first, setFirst] = useState<Pilot>();
  const [second, setSecond] = useState<Pilot>();
  const intent = useCreationIntent();
  const action = useAction();
  const wide = useWindowDimensions().width >= 720;
  const resource = useLoad(useCallback(() => preparation(client, scenario), [client, scenario]));
  const ready = !!first && !!second && first.id !== second.id && !!resource.data?.exercises.length && !!resource.data.competencies.items.length;
  const begin = () => action.run(async () => {
    if (!ready || !first || !second || !resource.data) return;
    const training = await createTraining(client, scenario, first, second, intent(scenario.scenarioDayModuleId, first.id, second.id));
    start({ scenario, pilots: [first, second], training, catalog: resource.data.competencies });
  });

