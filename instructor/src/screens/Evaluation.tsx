import { useState } from 'react';
import { View, useWindowDimensions } from 'react-native';
import type { Client } from '../api/client';
import { newScorecard, pilotName, type Assessment, type Receipt, type Scorecard, type Seat } from '../api/models';
import { submit } from '../api/training';
import { useAction } from '../hooks';
import { Action, Choice, Copy, Failure, Page, Panel, Row, Title } from '../ui';
import { AssessmentForm } from './Assessment';
import { Exercises } from './Exercises';
import type { Workspace } from './Setup';

function Participants({ workspace, seat, select }: { workspace: Workspace; seat: Seat; select: (s: Seat) => void }) {
  return <Row>{(['cm1', 'cm2'] as const).map((key, index) => <Choice key={key}
    label={key.toUpperCase() + ' · ' + pilotName(workspace.pilots[index])} selected={key === seat} onPress={() => select(key)}/>)}</Row>;
}

function complete(workspace: Workspace, card: Scorecard) {
  return [card.cm1, card.cm2].every(entry =>
    entry.result !== null && workspace.catalog.items.every(item => !!entry.grades[item.code]));
}

