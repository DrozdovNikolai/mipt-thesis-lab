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

