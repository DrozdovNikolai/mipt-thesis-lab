import { useCallback, useState } from 'react';
import type { Client } from '../api/client';
import { pilotName, type Pilot } from '../api/models';
import { pilots } from '../api/training';
import { useLoad } from '../hooks';
import { Action, Copy, Failure, Field, ListItem, Loading, Panel } from '../ui';

function details(pilot: Pilot) {
  return [pilot.position, pilot.aircraftCode, pilot.license].filter(Boolean).join(' · ');
}

function Results({ client, query, excluded, select }: {
  client: Client; query: string; excluded?: number; select: (pilot: Pilot) => void;
}) {
  const result = useLoad(useCallback(() => pilots(client, query), [client, query]));
  if (result.error) return <><Failure message={result.error}/><Action secondary label="Повторить поиск" onPress={result.retry}/></>;
  if (!result.data) return <Loading label="Поиск в справочнике…"/>;
  const eligible = result.data.filter(pilot => pilot.id !== excluded);
  if (!eligible.length) return <Copy muted>Участники не найдены</Copy>;
  return <>{eligible.map(pilot => <ListItem key={pilot.id} title={pilotName(pilot)} detail={details(pilot)} onPress={() => select(pilot)}/>)}</>;
}

function Selected({ pilot, clear }: { pilot: Pilot; clear: () => void }) {
  return <><Copy strong>{pilotName(pilot)}</Copy><Copy muted>{details(pilot)}</Copy>
    <Action secondary label="Изменить участника" onPress={clear}/></>;
}

export function CrewPicker({ client, seat, pilot, excluded, select }: {
  client: Client; seat: string; pilot?: Pilot; excluded?: number; select: (p?: Pilot) => void;
}) {
  const [term, setTerm] = useState('');
  return <Panel><Copy strong>{seat}</Copy>{pilot ? <Selected pilot={pilot} clear={() => { setTerm(''); select(); }}/>
    : <><Field label="Фамилия или номер свидетельства" value={term} onChangeText={setTerm}/>
      {term.trim().length >= 2 && <Results key={term} client={client} query={term} excluded={excluded} select={select}/>}</>}</Panel>;
}

