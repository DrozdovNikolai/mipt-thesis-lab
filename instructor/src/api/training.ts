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

