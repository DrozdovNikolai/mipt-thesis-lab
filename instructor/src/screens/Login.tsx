import { useState, type ReactNode } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, View } from 'react-native';
import { Client } from '../api/client';
import { useAction } from '../hooks';
import { Action, Brand, Failure, Field, Panel, Title } from '../ui';

function LoginFrame({ children }: { children: ReactNode }) {
  return <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
    <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ flexGrow: 1, justifyContent: 'center', alignItems: 'center', padding: 20 }}>
      <View style={{ width: '100%', maxWidth: 408, gap: 24 }}><Brand/>{children}</View>
    </ScrollView></KeyboardAvoidingView>;
}

function Credentials({ login, password, setLogin, setPassword, submit }: {
  login: string; password: string; setLogin: (v: string) => void; setPassword: (v: string) => void; submit: () => void;
}) {
  return <><Field label="Логин" value={login} onChangeText={setLogin} autoCapitalize="none" autoCorrect={false} autoComplete="username"/>
    <Field label="Пароль" value={password} onChangeText={setPassword} secureTextEntry autoComplete="current-password"
      returnKeyType="go" onSubmitEditing={submit}/></>;
}

async function signIn(login: string, password: string) {
  const client = await Client.login(login, password);
  const profile = await client.send<{login: string; isActive: boolean; mustChangePassword?: boolean}>('/auth/me');
  if (!profile.isActive || profile.mustChangePassword) {
    await client.logout();
    throw new Error(profile.mustChangePassword ? 'Смените пароль в основном приложении.' : 'Учётная запись отключена');
  }
  return { client, name: profile.login };
}

export function Login({ onLogin }: { onLogin: (client: Client, name: string) => void }) {
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const action = useAction();
  const valid = !!login.trim() && !!password;
  const submit = () => valid && action.run(async () => {
    const session = await signIn(login, password);
    onLogin(session.client, session.name);
  });
  return <LoginFrame><Panel><Title>Вход инструктора</Title>
    <Credentials {...{ login, password, setLogin, setPassword, submit }}/>
    <Failure message={action.error}/><Action label={action.busy ? 'Входим…' : 'Войти'} disabled={!valid || action.busy} onPress={submit}/>
  </Panel></LoginFrame>;
}

