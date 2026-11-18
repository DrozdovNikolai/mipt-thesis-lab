export interface Tokens {
  accessToken: string;
  refreshToken: string;
}

export interface Scenario {
  scenarioId: number;
  scenarioDayModuleId: number;
  title: string;
  code?: string;
  aircraftCode?: string;
  status: string;
}

export interface Pilot {
  id: number;
  firstName: string;
  lastName: string;
  position?: string;
  aircraftCode?: string;
  license?: string;
}

export interface Exercise {
  id: number;
  name: string;
  setup?: string;
  displayLabel?: string;
  stepLabel?: string;
  guidancePlainText?: string;
  guidance?: string;
  content?: { id: number; elements: string; details?: string }[];
  duration?: number;
  pf?: string;
  aircraft?: { acType?: string; engines?: string };
}

export interface Competency {
  id: number;
  code: string;
  name: string;
  indicators?: { id: number; code: string; name: string }[];
}

export interface Catalog {
  items: Competency[];
  gradingScale?: { values: { code: string; label?: string }[] } | null;
}

export interface Training {
  trainingId: number;
  cm1AssessmentId: number;
  cm2AssessmentId: number;
  exercises: Exercise[];
}

export type Seat = 'cm1' | 'cm2';
export interface Assessment {
  grades: Record<string, string>;
  summary: string;
  result: boolean | null;
}
export type Scorecard = Record<Seat, Assessment>;

export interface Receipt {
  trainingId: number;
  submissionStatus: string;
  submissionError?: string | null;
  assessmentsCompleted: boolean;
}

export function pilotName(pilot: Pilot) {
  return [pilot.lastName, pilot.firstName].filter(Boolean).join(' ') || `Участник №${pilot.id}`;
}

export function exerciseName(exercise: Exercise) {
  return exercise.displayLabel || exercise.name || exercise.setup || `Упражнение №${exercise.id}`;
}

export function newScorecard(): Scorecard {
  const blank = (): Assessment => ({ grades: {}, summary: '', result: null });
  return { cm1: blank(), cm2: blank() };
}

