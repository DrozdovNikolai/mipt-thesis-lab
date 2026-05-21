import type { ReactNode } from 'react';
import { ActivityIndicator, Image, Pressable, ScrollView, Text, TextInput, View, type TextInputProps } from 'react-native';

export const colors = {
  background: '#15181e', surface: '#20252d', border: '#39414e', text: '#f2f2f7',
  muted: '#acb5c3', accent: '#ffce00', error: '#ffaca6',
};

export function Copy({ children, muted, strong }: { children: ReactNode; muted?: boolean; strong?: boolean }) {
  return <Text style={{ color: muted ? colors.muted : colors.text, fontSize: 15, lineHeight: 22, fontWeight: strong ? '700' : '400' }}>{children}</Text>;
}

export function Title({ children, small }: { children: ReactNode; small?: boolean }) {
  return <Text accessibilityRole="header" style={{ fontSize: small ? 20 : 32, fontWeight: '700', color: colors.text }}>{children}</Text>;
}

