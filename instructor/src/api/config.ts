import { Platform } from 'react-native';

export const baseUrl = Platform.OS === 'web' && __DEV__ ? '/api' : (process.env.EXPO_PUBLIC_API_URL || 'https://session.55nord.ru/api').replace(/\/+$/, '');
