import React, { useState } from 'react';
import { StatusBar, View } from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import type { Client } from './src/api/client';
import type { Receipt, Scenario } from './src/api/models';
import { Login } from './src/screens/Login';
import { Scenarios } from './src/screens/Scenarios';
import { Setup, type Workspace } from './src/screens/Setup';
import { Evaluation } from './src/screens/Evaluation';
import { Result } from './src/screens/Result';
import { Action, Brand, colors, Copy, Failure, Row } from './src/ui';
import { useAction } from './src/hooks';

type Screen =
  | { page: 'scenarios' }
  | { page: 'setup'; scenario: Scenario }
  | { page: 'evaluation'; workspace: Workspace }
  | { page: 'result'; receipt: Receipt };

function Route({ client, screen, navigate }: { client: Client; screen: Screen; navigate: (s: Screen) => void }) {
  const home = () => navigate({ page: 'scenarios' });
  switch (screen.page) {
    case 'scenarios': return <Scenarios client={client} select={scenario => navigate({ page: 'setup', scenario })}/>;
    case 'setup': return <Setup client={client} scenario={screen.scenario} back={home} start={workspace => navigate({ page: 'evaluation', workspace })}/>;

case 'evaluation': return <Evaluation client={client} workspace={screen.workspace} finish={receipt => navigate({ page: 'result', receipt })}/>;
    case 'result': return <Result client={client} initial={screen.receipt} home={home}/>;
  }
}

function Header({ name, signOut, busy }: { name: string; signOut?: () => void; busy: boolean }) {
  return <View style={{ paddingHorizontal: 18, paddingVertical: 10, backgroundColor: colors.surface, borderBottomWidth: 1, borderColor: colors.border,
    flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
    <Brand/><Row><Copy muted>{name}</Copy>{signOut && <Action secondary label="Выйти" disabled={busy} onPress={signOut}/>}</Row>
  </View>;
}

function Instructor({ client, name, exit }: { client: Client; name: string; exit: () => void }) {
  React.useEffect(() => { client.onExpired = exit; return () => { client.onExpired = undefined; }; }, [client, exit]);
  const [screen, navigate] = useState<Screen>({ page: 'scenarios' });
  const action = useAction();
  return <><Header name={name} busy={action.busy} signOut={screen.page === 'scenarios' || screen.page === 'result'
    ? () => action.run(async () => { await client.logout(); exit(); }) : undefined}/>
    <Failure message={action.error}/><Route {...{ client, screen, navigate }}/></>;
}

export default function App() {
  const [session, setSession] = useState<{ client: Client; name: string }>();
  return <SafeAreaProvider><SafeAreaView style={{ flex: 1, backgroundColor: colors.background }}>
    <StatusBar barStyle="light-content"/>
    {session ? <Instructor {...session} exit={() => setSession(undefined)}/>
      : <Login onLogin={(client, name) => setSession({ client, name })}/>}
  </SafeAreaView></SafeAreaProvider>;
}

