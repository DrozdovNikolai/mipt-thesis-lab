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

