import { createI18n } from 'vue-i18n'

const resources = {
  en: {
    translation: {
      auth: {
        title: 'Authorization',
        login: 'Login',
        password: 'Password',
        signIn: 'Sign in',
        clear: 'Clear session',
        error: 'Auth error',
      },
      admin: {
        logout: 'Logout',
        description: 'Privilege-gated infrastructure route.',
      },
      routes: {
        home: 'Home',
        admin: 'Admin',
      },
      session: {
        user: 'User',
        privileges: 'Privileges',
      },
      statusLabel: 'Status',
      status: {
        idle: 'idle',
        authorized: 'authorized',
        unauthorized: 'unauthorized',
        loading: 'loading',
      },
      errors: {
        somethingWentWrong: 'Something went wrong',
        unexpectedError: 'An unexpected error occurred. Please try again.',
      },
      actions: {
        tryAgain: 'Try Again',
        goHome: 'Go Home',
      },
    },
  },
  ru: {
    translation: {
      auth: {
        title: 'Авторизация',
        login: 'Логин',
        password: 'Пароль',
        signIn: 'Войти',
        clear: 'Сбросить сессию',
        error: 'Ошибка авторизации',
      },
      admin: {
        logout: 'Выйти',
        description: 'Инфраструктурный маршрут с проверкой привилегий.',
      },
      routes: {
        home: 'Главная',
        admin: 'Админ',
      },
      session: {
        user: 'Пользователь',
        privileges: 'Привилегии',
      },
      statusLabel: 'Статус',
      status: {
        idle: 'idle',
        authorized: 'authorized',
        unauthorized: 'unauthorized',
        loading: 'loading',
      },
      errors: {
        somethingWentWrong: 'Что-то пошло не так',
        unexpectedError: 'Произошла непредвиденная ошибка. Повторите попытку.',
      },
      actions: {
        tryAgain: 'Попробовать снова',
        goHome: 'На главную',
      },
    },
  },
} as const

export const i18n = createI18n({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: { en: resources.en.translation, ru: resources.ru.translation },
})
