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

function ParticipantSummary({ name, card }: { name: string; card: Assessment }) {
  return <Panel><Title small>{name}</Title><Copy>{Object.entries(card.grades).map(([code, value]) => code + ' ' + value).join('   ·   ')}</Copy>
    {!!card.summary && <Copy>{card.summary}</Copy>}<Copy strong>{card.result ? 'Зачёт' : 'Незачёт'}</Copy></Panel>;
}

function Review({ workspace, card, send, back, busy, error }: {
  workspace: Workspace; card: Scorecard; send: () => void; back: () => void; busy: boolean; error: string;
}) {
  return <Page><Title>Проверка оценок</Title><Copy muted>{workspace.scenario.title} · № {workspace.training.trainingId}</Copy>
    <ParticipantSummary name={pilotName(workspace.pilots[0])} card={card.cm1}/>
    <ParticipantSummary name={pilotName(workspace.pilots[1])} card={card.cm2}/>
    <Failure message={error}/><Action label={busy ? 'Отправляем…' : 'Отправить оценки'} onPress={send} disabled={busy}/>
    <Action secondary label="Вернуться к оцениванию" onPress={back} disabled={busy}/>
  </Page>;
}

export function Evaluation({ client, workspace, finish }: {
  client: Client; workspace: Workspace; finish: (receipt: Receipt) => void;
}) {
  const [seat, select] = useState<Seat>('cm1');
  const [card, setCard] = useState(newScorecard);
  const [review, setReview] = useState(false);
  const action = useAction();
  const wide = useWindowDimensions().width >= 850;
  const change = (updated: Assessment) => setCard(old => ({ ...old, [seat]: updated }));

if (review) return <Review {...{ workspace, card, busy: action.busy, error: action.error }}
    send={() => action.run(async () => finish(await submit(client, workspace.training, card)))} back={() => setReview(false)}/>;

return <Page><Title>{workspace.scenario.title}</Title><Copy muted>Тренировка № {workspace.training.trainingId}</Copy>
    <Participants workspace={workspace} seat={seat} select={select}/>
    <View style={{ flexDirection: wide ? 'row' : 'column', gap: 16 }}>
      <View style={{ flex: 1 }}><Exercises items={workspace.training.exercises}/></View>
      <View style={{ flex: 2 }}><AssessmentForm key={seat} catalog={workspace.catalog} card={card[seat]} change={change}/></View>
    </View>

{!complete(workspace, card) && <Copy muted>Для отправки оцените компетенции и выберите итог для обоих пилотов.</Copy>}
    <Action label="Проверить оценки" disabled={!complete(workspace, card)} onPress={() => setReview(true)}/>
  </Page>;
}

