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

