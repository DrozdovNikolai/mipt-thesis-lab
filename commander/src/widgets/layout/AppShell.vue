<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import { useSessionService } from '@/app/context'
import { navigation } from '@/app/navigation'
import AppSidebar from './ui/AppSidebar.vue'
import AppHeader from './ui/AppHeader.vue'

const session = useSessionService()
const route = useRoute()
const mainScroll = ref<HTMLElement | null>(null)
const visibleItems = computed(() =>
  navigation.filter((item) => session.store.hasAllPrivileges(item.privileges)),
)
watch(
  () => route.path,
  () => mainScroll.value?.scrollTo({ top: 0, left: 0, behavior: 'auto' }),
)
</script>

<template>
  <div class="min-h-screen bg-app md:h-screen md:overflow-hidden">
    <div class="flex min-h-screen flex-col md:h-full md:min-h-0 md:flex-row">
      <AppSidebar :items="visibleItems" />
      <div class="flex min-h-0 min-w-0 flex-1 flex-col">
        <AppHeader
          :user-label="session.store.user?.login ?? session.store.user?.email ?? 'Unknown user'"
          @logout="session.logout"
        />
        <main
          ref="mainScroll"
          class="app-shell-scroll-area flex-1 p-4 md:min-h-0 md:overflow-y-scroll md:p-2"
        >
          <div class="w-full min-w-0"><RouterView /></div>
        </main>
      </div>
    </div>
  </div>
</template>
