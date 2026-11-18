import * as Crypto from 'expo-crypto';
import { Client } from './client';
import type { Assessment, Catalog, Exercise, Pilot, Receipt, Scenario, Scorecard, Training } from './models';

export async function scenarios(client: Client) {
  const response = await client.send<{items: Scenario[]}>('/training/assessment/scenarios');
  return response.items.filter(item => item.status?.trim().toUpperCase() === 'PUBLISHED');
}

export async function plan(client: Client, day: number) {
  const response = await client.send<{exercises: Exercise[]}>(`/training/assessment/scenario-days/${day}/exercises`);
  return response.exercises;
}

export async function pilots(client: Client, query: string) {
  if (query.trim().length < 2) return [];
  const response = await client.send<{items: Pilot[]}>(`/training/users/search?q=${encodeURIComponent(query.trim())}&limit=8`);
  return response.items;
}

export function catalog(client: Client) {
  return client.send<Catalog>('/training/competencies');
}

export function creationId() {
  const time = Date.now().toString(16).padStart(12, '0');
  const random = Crypto.randomUUID();
  return `${time.slice(0, 8)}-${time.slice(8)}-7${random.slice(15, 18)}${random.slice(18)}`;
}

export async function createTraining(client: Client, scenario: Scenario, first: Pilot, second: Pilot, clientCreationId: string) {
  const data = await client.send<Training & {
    commentContract?: { version: number }; clientCreationId?: string;
  }>('/training/trainings', {
    scenarioId: scenario.scenarioId,
    scenarioDayModuleId: scenario.scenarioDayModuleId,
    cm1Id: first.id, cm2Id: second.id, clientCreationId,
  });
  if ((data.commentContract?.version ?? 0) !== 0 || (data.clientCreationId && data.clientCreationId !== clientCreationId)) {
    throw new Error('Сервер вернул несовместимый контракт тренировки');
  }
  if (!data.trainingId || !data.cm1AssessmentId || !data.cm2AssessmentId || !Array.isArray(data.exercises)) {
    throw new Error('В ответе сервера отсутствуют данные тренировки');
  }
  return data;
}

function assessmentBlock(assessmentId: number, card: Assessment) {
  if (card.result === null) throw new Error('Выберите итог для каждого пилота');
  return { assessmentId, grades: card.grades, mistakeReports: [], summary: card.summary.trim(), result: card.result };
}

export async function submit(client: Client, training: Training, card: Scorecard) {
  const body = {
    cm1: assessmentBlock(training.cm1AssessmentId, card.cm1),
    cm2: assessmentBlock(training.cm2AssessmentId, card.cm2),
  };
  const idempotencyKey = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256, `submit:${training.trainingId}:${JSON.stringify(body)}`,
  );
  return client.send<Receipt>(`/training/trainings/${training.trainingId}/submit`, { ...body, idempotencyKey });
}

export function submissionStatus(client: Client, trainingId: number) {
  return client.send<Receipt>(`/training/trainings/${trainingId}/submit-status`);
}

export function gradeOptions(data: Catalog) {
  return data.gradingScale?.values?.length ? data.gradingScale.values : ['5','4','3','2','1'].map(code => ({ code, label: code }));
}

