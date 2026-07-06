import { useState, type ReactNode } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, View } from 'react-native';
import { Client } from '../api/client';
import { useAction } from '../hooks';
import { Action, Brand, Copy, Failure, Field, Panel, Title } from '../ui';

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

