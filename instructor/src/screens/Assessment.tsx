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

