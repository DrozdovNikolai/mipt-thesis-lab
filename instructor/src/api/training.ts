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

export function createTraining(client: Client, scenario: Scenario, first: Pilot, second: Pilot, clientCreationId: string) {
  return client.send<Training>('/training/trainings', {
    scenarioId: scenario.scenarioId,
    scenarioDayModuleId: scenario.scenarioDayModuleId,
    cm1Id: first.id, cm2Id: second.id, clientCreationId,
  });
}

