import { useState } from 'react';
import { exerciseName, type Exercise } from '../api/models';
import { Choice, Copy, Panel, Row, Title } from '../ui';

function Briefing({ exercise }: { exercise: Exercise }) {
  return <><Title small>{exerciseName(exercise)}</Title>
    {!!exercise.setup && exercise.setup !== exerciseName(exercise) && <Copy>{exercise.setup}</Copy>}
    {!!exercise.pf && <Copy muted>Пилотирующий · {exercise.pf}</Copy>}
    <Copy>{exercise.guidancePlainText || exercise.guidance || 'Указания к упражнению отсутствуют'}</Copy></>;
}

function Rail({ items, current, choose }: { items: Exercise[]; current: number; choose: (index: number) => void }) {
  return <Row>{items.map((item, index) => <Choice key={item.id} selected={index === current}
    label={item.stepLabel || String(index + 1)} onPress={() => choose(index)}/>)}</Row>;
}

export function Exercises({ items }: { items: Exercise[] }) {
  const [current, choose] = useState(0);
  const item = items[current];
  return <Panel><Copy muted>Упражнения · {items.length}</Copy>
    <Rail items={items} current={current} choose={choose}/>
    {item ? <Briefing exercise={item}/> : <Copy muted>Сервер вернул пустой план тренировки</Copy>}
  </Panel>;
}

