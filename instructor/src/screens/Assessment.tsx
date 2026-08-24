import { useState } from 'react';
import { View } from 'react-native';
import type { Assessment, Catalog, Competency } from '../api/models';
import { gradeOptions } from '../api/training';
import { Choice, Copy, Field, Panel, Row, Title } from '../ui';

function Scale({ catalog, value, choose }: { catalog: Catalog; value?: string; choose: (grade: string) => void }) {
  return <Row>{gradeOptions(catalog).map(grade => <Choice key={grade.code} label={grade.label || grade.code}
    selected={grade.code === value} onPress={() => choose(grade.code)}/>)}</Row>;
}

function Indicators({ competency }: { competency: Competency }) {
  const [open, toggle] = useState(false);
  if (!competency.indicators?.length) return null;
  return <><Row><Choice label="Индикаторы" selected={open} onPress={() => toggle(!open)}/></Row>
    {open && competency.indicators.map(item => <Copy key={item.id} muted>{item.code} · {item.name}</Copy>)}</>;
}

function GradeRow({ item, catalog, card, change }: {
  item: Competency; catalog: Catalog; card: Assessment; change: (value: Assessment) => void;
}) {
  return <Panel><Copy strong>{item.code} · {item.name}</Copy><Indicators competency={item}/>
    <Scale catalog={catalog} value={card.grades[item.code]} choose={grade => change({ ...card, grades: { ...card.grades, [item.code]: grade } })}/>
  </Panel>;
}

function Outcome({ value, choose }: { value: boolean | null; choose: (v: boolean) => void }) {
  return <><Copy strong>Итог тренировки</Copy><Row>
    <Choice label="Зачёт" selected={value === true} onPress={() => choose(true)}/>
    <Choice label="Незачёт" selected={value === false} onPress={() => choose(false)}/>
  </Row></>;
}

function Conclusion({ card, change }: { card: Assessment; change: (v: Assessment) => void }) {
  return <Panel><Field label="Заключение инструктора" multiline value={card.summary}
    onChangeText={summary => change({ ...card, summary })}/>
    <Outcome value={card.result} choose={result => change({ ...card, result })}/></Panel>;
}

export function AssessmentForm({ catalog, card, change }: {
  catalog: Catalog; card: Assessment; change: (v: Assessment) => void;
}) {
  return <View style={{ gap: 12 }}><Title small>Компетенции</Title>
    {catalog.items.map(item => <GradeRow key={item.id} {...{ item, catalog, card, change }}/>)}
    <Conclusion card={card} change={change}/>
  </View>;
}

