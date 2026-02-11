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
  duration?: number;
  pf?: string;
}

