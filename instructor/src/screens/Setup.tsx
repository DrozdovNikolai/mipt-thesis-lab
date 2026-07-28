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

