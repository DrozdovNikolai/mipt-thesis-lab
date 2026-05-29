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

export function Action({ label, onPress, secondary, disabled }: {
  label: string; onPress: () => void; secondary?: boolean; disabled?: boolean;
}) {
  return <Pressable accessibilityRole="button" accessibilityState={{ disabled }} disabled={disabled} onPress={onPress}
    style={({ pressed }) => ({ minHeight: 44, justifyContent: 'center', alignItems: 'center', paddingHorizontal: 16,
      borderRadius: 8, borderWidth: 1, borderColor: secondary ? colors.border : colors.accent,
      backgroundColor: secondary ? colors.surface : colors.accent, opacity: disabled ? 0.42 : pressed ? 0.74 : 1 })}>
    <Text style={{ fontWeight: '700', color: secondary ? colors.text : colors.background }}>{label}</Text>
  </Pressable>;
}

export function Choice({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  return <Pressable accessibilityRole="button" accessibilityState={{ selected }} onPress={onPress}
    style={{ paddingVertical: 11, paddingHorizontal: 14, borderWidth: 1, borderRadius: 7,
      backgroundColor: selected ? colors.accent : colors.background, borderColor: selected ? colors.accent : colors.border }}>
    <Text style={{ color: selected ? colors.background : colors.text, fontWeight: '600' }}>{label}</Text>
  </Pressable>;
}

export function Field({ label, ...props }: TextInputProps & { label: string }) {
  return <View style={{ gap: 6 }}><Copy muted>{label}</Copy>
    <TextInput accessibilityLabel={label} placeholderTextColor={colors.muted} selectionColor={colors.accent} {...props}
      style={{ color: colors.text, backgroundColor: colors.background, borderColor: colors.border, borderWidth: 1,
        borderRadius: 7, minHeight: props.multiline ? 90 : 48, padding: 12, fontSize: 16, textAlignVertical: props.multiline ? 'top' : 'center' }}/>
  </View>;
}

