<template>
  <div class="space-y-6">
    <div>
      <h2 class="text-2xl font-bold text-gray-900">Kernel Management</h2>
      <p class="text-sm text-gray-500">Manage kernel backend, operating mode, and transport protocols</p>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      
      <!-- Backend Selection -->
      <div class="bg-white rounded-2xl p-6 shadow-sm border border-gray-100">
        <h3 class="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
          <ServerStackIcon class="w-5 h-5 text-indigo-500" />
          Backend Kernel
        </h3>
        
        <div class="space-y-3">
          <button 
            @click="switchBackend('usque')"
            class="w-full text-left p-4 rounded-xl border transition-all duration-200 flex items-center justify-between group"
            :class="backend === 'usque' ? 'bg-indigo-50 border-indigo-200 ring-1 ring-indigo-200' : 'bg-white border-gray-200 hover:border-indigo-300 hover:shadow-sm'"
            :disabled="isLoading"
          >
            <div>
              <span class="block text-sm font-bold" :class="backend === 'usque' ? 'text-indigo-900' : 'text-gray-700'">USQUE</span>
              <span class="text-xs text-gray-500 mt-0.5 flex items-center gap-2">
                Lightweight, specialized client
                <span v-if="versionMap.usque?.installed_version" class="font-mono bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded text-[10px]">v{{ versionMap.usque.installed_version }}</span>
              </span>
            </div>
            <div class="w-5 h-5 rounded-full border flex items-center justify-center" :class="backend === 'usque' ? 'border-indigo-500 bg-indigo-500' : 'border-gray-300'">
              <CheckIcon v-if="backend === 'usque'" class="w-3 h-3 text-white" />
            </div>
          </button>

          <button 
            @click="switchBackend('official')"
            class="w-full text-left p-4 rounded-xl border transition-all duration-200 flex items-center justify-between group"
            :class="backend === 'official' ? 'bg-orange-50 border-orange-200 ring-1 ring-orange-200' : 'bg-white border-gray-200 hover:border-orange-300 hover:shadow-sm'"
            :disabled="isLoading"
          >
            <div>
              <span class="block text-sm font-bold" :class="backend === 'official' ? 'text-orange-900' : 'text-gray-700'">Official Client</span>
              <span class="text-xs text-gray-500 mt-0.5 flex items-center gap-2">
                Standard Cloudflare WARP client
                <span v-if="versionMap.official?.installed_version" class="font-mono bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded text-[10px]">v{{ versionMap.official.installed_version }}</span>
              </span>
            </div>
            <div class="w-5 h-5 rounded-full border flex items-center justify-center" :class="backend === 'official' ? 'border-orange-500 bg-orange-500' : 'border-gray-300'">
              <CheckIcon v-if="backend === 'official'" class="w-3 h-3 text-white" />
            </div>
          </button>
        </div>
      </div>



      <!-- Protocol Selection -->
      <div class="bg-white rounded-2xl p-6 shadow-sm border border-gray-100">
        <h3 class="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
          <ShieldCheckIcon class="w-5 h-5 text-blue-500" />
          Transport Protocol
        </h3>
        
        <div class="p-4 rounded-xl border mb-4" :class="canSwitchProtocol ? 'bg-blue-50 border-blue-100' : 'bg-gray-50 border-gray-100 opacity-75'">
          <div class="flex items-center justify-between mb-2">
            <span class="text-sm font-medium text-gray-900">Current Protocol</span>
            <span class="text-xs font-mono px-2 py-0.5 rounded bg-white border border-gray-200 font-bold" :class="canSwitchProtocol ? 'text-blue-700' : 'text-gray-500'">{{ currentProtocol }}</span>
          </div>
          
          <p class="text-xs text-gray-500 mb-4">
            MASQUE is the modern standard. WireGuard is legacy but may be faster.
          </p>

          <button 
            v-if="canSwitchProtocol"
            @click="toggleProtocol"
            :disabled="isLoading"
            class="w-full py-2 px-4 rounded-lg bg-white border border-blue-200 text-blue-700 text-sm font-medium hover:bg-blue-50 transition-colors shadow-sm"
          >
            Switch to {{ currentProtocol === 'MASQUE' ? 'WireGuard' : 'MASQUE' }}
          </button>
        </div>
      </div>

      <!-- Version Management -->
      <div class="bg-white rounded-2xl p-6 shadow-sm border border-gray-100">
        <h3 class="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
          <ArchiveBoxIcon class="w-5 h-5 text-purple-500" />
          Kernel Version
        </h3>

        <div class="p-4 rounded-xl border bg-purple-50 border-purple-100">
          <div class="flex items-center justify-between mb-4">
            <span class="text-sm font-medium text-purple-900">Current Version</span>
            <span class="text-xs font-mono px-2 py-0.5 rounded bg-white border border-purple-200 font-bold text-purple-700">
              {{ versionData.current || 'Unknown' }}
            </span>
          </div>

          <div v-if="backend === 'usque'">
            <label class="block text-xs font-medium text-purple-800 mb-1.5">Select Version</label>
            <div class="flex gap-2">
              <select 
                :value="versionData.current"
                @change="switchVersion($event.target.value)"
                :disabled="isLoading || versionData.versions.length <= 1"
                class="flex-1 text-sm rounded-lg border-purple-200 focus:border-purple-500 focus:ring-purple-500 bg-white"
              >
                <option v-for="v in versionData.versions" :key="v" :value="v">
                  {{ v }}
                </option>
                <option v-if="versionData.versions.length === 0" disabled>No versions found</option>
              </select>
              
              <button 
                @click="checkForUpdates"
                :disabled="isCheckingUpdate"
                class="px-3 py-2 rounded-lg border border-purple-200 bg-white text-purple-700 hover:bg-purple-50 text-xs font-medium transition-colors"
                title="Check for updates"
              >
                <span v-if="isCheckingUpdate" class="animate-spin inline-block">↻</span>
                <span v-else>Check</span>
              </button>
            </div>

            <!-- Update Available Notification -->
            <div v-if="versionData.update_available" class="mt-3 p-3 rounded-lg bg-green-50 border border-green-200 flex items-start gap-3">
              <div class="flex-1">
                <p class="text-xs font-bold text-green-800">New version available: {{ versionData.latest_version }}</p>
                <p class="text-[10px] text-green-600 mt-0.5">
                  Current installed: {{ versionData.installed_version }}
                </p>
              </div>
              <button 
                @click="performUpdate"
                :disabled="isUpdating"
                class="px-3 py-1.5 rounded-md bg-green-600 text-white text-xs font-bold hover:bg-green-700 shadow-sm disabled:opacity-50"
              >
                {{ isUpdating ? 'Updating...' : 'Update' }}
              </button>
            </div>
            
            <p v-else-if="versionData.latest_version" class="text-[10px] text-gray-400 mt-2 flex items-center gap-1">
              <CheckIcon class="w-3 h-3" />
              Latest version installed ({{ versionData.latest_version }})
            </p>

            <p class="text-[10px] text-purple-600 mt-2" v-if="!versionData.update_available">
              Switching versions will restart the kernel.
            </p>
          </div>
          <div v-else>
             <p class="text-xs text-purple-700 bg-white p-3 rounded border border-purple-100">
               Version management is handled by the system package manager for the Official Client.
             </p>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue';
import axios from 'axios';
import { 
  ServerStackIcon, 
  CpuChipIcon, 
  ShieldCheckIcon,
  CheckIcon,
  ArchiveBoxIcon
} from '@heroicons/vue/24/outline';

const statusData = ref({});
const versionData = ref({ versions: [], current: '', installed_version: '', latest_version: '', update_available: false });
const isLoading = ref(false);
const isCheckingUpdate = ref(false);
const isUpdating = ref(false);
let socket = null;

const isDocker = computed(() => statusData.value.is_docker || false);
const backend = computed(() => statusData.value.backend || 'usque');
const warpMode = computed(() => statusData.value.warp_mode || 'proxy');
const currentProtocol = computed(() => statusData.value.warp_protocol || statusData.value.protocol || 'MASQUE');
const canSwitchProtocol = computed(() => backend.value === 'official' && warpMode.value === 'tun');

const apiCall = async (method, url, data = null) => {
  try {
    const response = await axios[method](url, data);
    return response.data;
  } catch (err) {
    console.error(`API Error (${method} ${url}):`, err);
    alert(err.response?.data?.detail || 'Operation failed');
    return null;
  }
};

const versionMap = ref({});

const fetchAllVersions = async () => {
  const data = await apiCall('get', '/api/kernel/all-versions');
  if (data) {
    versionMap.value = data;
    // Also update current selected version data if needed
    if (data[backend.value]) {
       const b = data[backend.value];
       versionData.value = {
        versions: b.versions || [],
        current: b.current || 'Unknown',
        installed_version: b.installed_version || '',
        latest_version: b.latest_version || '',
        update_available: b.update_available || false
       };
    }
  }
};

const fetchVersions = async () => {
    // Legacy method, kept for compatibility if needed, but fetchAllVersions covers it mostly.
    // Actually we can just call fetchAllVersions
    await fetchAllVersions();
};

const checkForUpdates = async () => {
  isCheckingUpdate.value = true;
  const res = await apiCall('post', '/api/kernel/check-update', { backend: backend.value });
  await fetchVersions();
  isCheckingUpdate.value = false;
  
  if (res && res.success) {
    // Optionally notify user via toast, but UI will update
  } else {
    alert(res?.message || 'No update found or check failed');
  }
};

const performUpdate = async () => {
  if (!confirm(`Download and install update ${versionData.value.latest_version}? The kernel will restart.`)) return;
  
  isUpdating.value = true;
  const res = await apiCall('post', '/api/kernel/update', { backend: backend.value });
  
  if (res && res.success) {
    await fetchVersions();
    alert('Update successful!');
  } else {
    alert(res?.message || 'Update failed');
  }
  isUpdating.value = false;
};

const switchVersion = async (newVersion) => {
  if (versionData.value.current === newVersion) return;
  if (!confirm(`Switch kernel version to ${newVersion}? This will restart the kernel.`)) return;
  
  isLoading.value = true;
  await apiCall('post', '/api/kernel/version', { backend: backend.value, version: newVersion });
  await fetchVersions();
  setTimeout(() => isLoading.value = false, 1500);
};

const switchBackend = async (newBackend) => {
  if (backend.value === newBackend) return;
  if (!confirm(`Switch backend to ${newBackend}? This will reconnect WARP.`)) return;
  isLoading.value = true;
  await apiCall('post', '/api/backend/switch', { backend: newBackend });
  // Version fetch will be triggered by watcher
  setTimeout(() => isLoading.value = false, 1500);
};

const switchMode = async (newMode) => {
  if (warpMode.value === newMode) return;
  if (!confirm(`Switch to ${newMode.toUpperCase()} mode? This will reconnect WARP.`)) return;
  isLoading.value = true;
  await apiCall('post', '/api/config/mode', { mode: newMode });
  setTimeout(() => isLoading.value = false, 1500);
};

const toggleProtocol = async () => {
  if (!canSwitchProtocol.value) return;
  const newProtocol = currentProtocol.value === 'MASQUE' ? 'wireguard' : 'masque';
  if (!confirm(`Switch protocol to ${newProtocol}?`)) return;
  
  isLoading.value = true;
  await apiCall('post', '/api/config/protocol', { protocol: newProtocol });
  setTimeout(() => isLoading.value = false, 1500);
};

// Watch backend change to fetch versions
watch(backend, () => {
  fetchVersions();
});

// WebSocket for status sync
const connectWebSocket = () => {
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${wsProtocol}//${window.location.host}/ws/status`;
  socket = new WebSocket(wsUrl);
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === 'status') {
      statusData.value = message.data;
    }
  };
  socket.onclose = () => {
    setTimeout(connectWebSocket, 3000);
  };
};

onMounted(() => {
  connectWebSocket();
  fetchVersions();
});

onUnmounted(() => {
  if (socket) socket.close();
});
</script>
