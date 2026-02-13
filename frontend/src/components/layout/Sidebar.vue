<template>
  <aside 
    class="fixed inset-y-0 left-0 z-50 w-64 h-screen bg-white/90 backdrop-blur-xl border-r border-orange-100 flex flex-col shadow-2xl shadow-orange-500/5 transition-transform duration-300 md:translate-x-0 md:static md:shadow-none"
    :class="isOpen ? 'translate-x-0' : '-translate-x-full'"
  >
    <!-- Mobile Close Button -->
    <button 
      @click="$emit('close')" 
      class="absolute top-4 right-4 md:hidden p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
    >
      <XMarkIcon class="w-5 h-5" />
    </button>

    <!-- Logo Section -->
    <div class="p-6 flex items-center gap-3">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-orange-500 via-orange-600 to-red-500 flex items-center justify-center shadow-lg shadow-orange-500/20 ring-1 ring-white/50">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
      </div>
      <div>
        <h1 class="text-xl font-bold text-gray-900 tracking-tight">Warp<span class="text-orange-600">Pool</span></h1>
        <p class="text-[10px] text-gray-500 font-medium tracking-wide uppercase">Manager</p>
      </div>
    </div>

    <!-- Navigation -->
    <nav class="flex-1 px-4 py-6 space-y-2">
      <router-link 
        v-for="item in navItems" 
        :key="item.path" 
        :to="item.path"
        class="flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 group relative overflow-hidden"
        :class="$route.path === item.path ? 'bg-orange-50 text-orange-700 shadow-sm ring-1 ring-orange-200' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'"
      >
        <div 
          v-if="$route.path === item.path"
          class="absolute left-0 top-0 bottom-0 w-1 bg-orange-500 rounded-l-xl"
        ></div>
        
        <component :is="item.icon" class="w-5 h-5 transition-transform group-hover:scale-110" :class="$route.path === item.path ? 'text-orange-600' : 'text-gray-400 group-hover:text-gray-600'" />
        <span class="font-medium text-sm">{{ item.name }}</span>
        
        <div v-if="$route.path === item.path" class="absolute right-3 w-1.5 h-1.5 rounded-full bg-orange-500"></div>
      </router-link>
    </nav>

    <!-- Footer / Version -->
    <div class="p-6 border-t border-gray-100 bg-gray-50/50">
      <div class="flex items-center gap-3">
        <div class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse shadow-[0_0_8px_rgba(16,185,129,0.5)]"></div>
        <p class="text-xs font-medium text-gray-500">System Online</p>
        <span class="ml-auto text-[10px] text-gray-400 font-mono bg-white px-2 py-0.5 rounded-full border border-gray-100 shadow-sm">{{ version }}</span>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { 
  HomeIcon, 
  Cog6ToothIcon, 
  CommandLineIcon,
  CpuChipIcon,
  XMarkIcon
} from '@heroicons/vue/24/outline';
import { ref, onMounted } from 'vue';

defineProps({
  isOpen: Boolean
});

defineEmits(['close']);

const navItems = [
  { name: 'Dashboard', path: '/', icon: HomeIcon },
  { name: 'Kernel', path: '/kernel', icon: CpuChipIcon },
  { name: 'Logs', path: '/logs', icon: CommandLineIcon },
  { name: 'Settings', path: '/settings', icon: Cog6ToothIcon },
];

const version = ref('...');

onMounted(async () => {
  try {
    // Determine API base - if in dev mode (Vite typically proxies /api, but if not we might need full URL)
    // Assuming Vite proxy is set up or relative path works (which it should if served by same backend or proxy)
    const res = await fetch('/api/version');
    if (res.ok) {
        const data = await res.json();
        // Ensure v prefix
        version.value = data.version.startsWith('v') ? data.version : `v${data.version}`;
    }
  } catch (e) {
    console.error("Failed to fetch version:", e);
    version.value = 'Unknown';
  }
});
</script>
