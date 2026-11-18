import { useCallback, useState } from 'react';
import type { Client } from '../api/client';
import type { Scenario } from '../api/models';
import { scenarios } from '../api/training';
import { useLoad } from '../hooks';
import { Action, Copy, Failure, Field, ListItem, Loading, Page, Title } from '../ui';

function matches(item: Scenario, query: string) {
  return [item.title, item.code, item.aircraftCode].join(' ').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
}

function ScenarioList({ items, select }: { items: Scenario[]; select: (item: Scenario) => void }) {
  if (!items.length) return <Copy muted>Сценарии не найдены</Copy>;
  return <>{items.map(item => <ListItem key={item.scenarioDayModuleId} title={item.title}
    detail={[item.code, item.aircraftCode].filter(Boolean).join(' · ')} onPress={() => select(item)}/>)}</>;
}

export function Scenarios({ client, select }: { client: Client; select: (item: Scenario) => void }) {
  const [query, setQuery] = useState('');
  const resource = useLoad(useCallback(() => scenarios(client), [client]));
  return <Page><Title>Сценарии тренировок</Title><Field label="Поиск сценария" value={query} onChangeText={setQuery}/>
    {resource.data ? <ScenarioList items={resource.data.filter(item => matches(item, query))} select={select}/>
      : resource.error ? <><Failure message={resource.error}/><Action label="Повторить" secondary onPress={resource.retry}/></>
      : <Loading label="Загрузка сценариев…"/>}
  </Page>;
}

