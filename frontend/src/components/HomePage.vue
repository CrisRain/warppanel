<template>
  <div class="min-h-screen bg-gradient-to-br from-orange-50 via-white to-orange-50 text-gray-800 font-sans overflow-hidden relative">
    
    <!-- Animated Background -->
    <div class="absolute inset-0 overflow-hidden pointer-events-none">
      <div class="absolute top-[-20%] left-[-10%] w-[60%] h-[60%] bg-gradient-to-br from-orange-200/30 via-orange-300/20 to-transparent rounded-full blur-3xl animate-float"></div>
      <div class="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] bg-gradient-to-tl from-orange-300/25 via-orange-200/20 to-transparent rounded-full blur-3xl animate-float-delayed"></div>
      <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[40%] h-[40%] bg-gradient-to-r from-orange-100/30 to-orange-200/20 rounded-full blur-3xl animate-pulse-slow"></div>
    </div>

    <!-- Main Container -->
    <div class="relative z-10 min-h-screen flex flex-col">
      
      <!-- Header -->
      <header class="px-6 py-5 backdrop-blur-md bg-white/80 border-b border-orange-200/50 shadow-sm">
        <div class="max-w-7xl mx-auto flex justify-between items-center">
          <div class="flex items-center gap-3">
            <div class="w-11 h-11 rounded-2xl bg-gradient-to-br from-orange-400 via-orange-500 to-orange-600 flex items-center justify-center shadow-lg shadow-orange-500/30 ring-2 ring-orange-400/20">
              <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <div>
              <h1 class="text-xl font-bold tracking-tight text-gray-900">Warp<span class="bg-gradient-to-r from-orange-500 to-orange-600 bg-clip-text text-transparent">Panel</span></h1>
              <p class="text-xs text-gray-500">Secure Connection Manager</p>
            </div>
          </div>
          <div class="flex items-center gap-3">
            <!-- Backend Selector -->
            <div class="relative group z-50">
              <button 
                class="flex items-center gap-2 text-xs font-medium px-3 py-2 rounded-full border backdrop-blur-md shadow-sm transition-all duration-200"
                :class="backend === 'usque' ? 'bg-indigo-50 text-indigo-700 border-indigo-200' : 'bg-gray-50 text-gray-700 border-gray-200'"
              >
                <span class="w-1.5 h-1.5 rounded-full" :class="backend === 'usque' ? 'bg-indigo-500' : 'bg-gray-400'"></span>
                <span class="uppercase tracking-wider">{{ backend }}</span>
                <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                </svg>
              </button>
              
              <!-- Dropdown -->
              <div class="absolute right-0 top-full mt-2 w-40 bg-white rounded-xl shadow-xl border border-gray-100 overflow-hidden opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 transform origin-top-right">
                <div class="p-1">
                  <button 
                    @click="switchBackend('usque')"
                    class="w-full text-left px-3 py-2 text-xs font-medium rounded-lg transition-colors flex items-center justify-between"
                    :class="backend === 'usque' ? 'bg-indigo-50 text-indigo-700' : 'text-gray-600 hover:bg-gray-50'"
                  >
                    <span>USQUE (Default)</span>
                    <svg v-if="backend === 'usque'" xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                    </svg>
                  </button>
                  <button 
                    @click="switchBackend('official')"
                    class="w-full text-left px-3 py-2 text-xs font-medium rounded-lg transition-colors flex items-center justify-between"
                    :class="backend === 'official' ? 'bg-orange-50 text-orange-700' : 'text-gray-600 hover:bg-gray-50'"
                  >
                    <span>Official Client</span>
                    <svg v-if="backend === 'official'" xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                    </svg>
                  </button>
                </div>
              </div>
            </div>

            <div class="flex items-center gap-2 text-xs font-medium text-gray-600 bg-orange-50 px-4 py-2 rounded-full border border-orange-200/70 backdrop-blur-md shadow-sm">
            <div class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse shadow-sm shadow-emerald-400/50"></div>
            <span>v1.3.0</span>
          </div>
          </div>
        </div>
      </header>

      <!-- Main Content -->
      <main class="flex-1 flex items-center justify-center px-6 py-12">
        <div class="w-full max-w-5xl">
          
          <!-- Status Section -->
          <div class="flex flex-col items-center mb-12">
            <!-- Connection Button -->
            <div class="relative mb-8">
              <!-- Animated Glow -->
              <div 
                class="absolute -inset-4 rounded-full opacity-50 blur-2xl transition-all duration-700"
                :class="isConnected ? 'bg-gradient-to-r from-emerald-300 via-green-400 to-emerald-500 animate-glow' : 'bg-gradient-to-r from-gray-300 via-gray-400 to-gray-300'"
              ></div>
              
              <!-- Button -->
              <button 
                @click="toggleConnection" 
                :disabled="isLoading"
                class="relative w-60 h-60 rounded-full flex flex-col items-center justify-center transition-all duration-500 group"
                :class="[
                  isLoading ? 'cursor-wait' : 'hover:scale-105 active:scale-95 cursor-pointer'
                ]"
              >
                <!-- Background -->
                <div 
                  class="absolute inset-0 rounded-full transition-all duration-700 shadow-2xl"
                  :class="isConnected ? 'bg-gradient-to-br from-emerald-400 to-green-500 shadow-emerald-400/40' : 'bg-gradient-to-br from-gray-200 to-gray-300 shadow-gray-400/30'"
                ></div>
                
                <!-- Inner Ring -->
                <div 
                  class="absolute inset-3 rounded-full bg-white flex items-center justify-center transition-all duration-700"
                  :class="isConnected ? 'shadow-2xl shadow-emerald-500/20' : 'shadow-2xl shadow-gray-400/20'"
                >
                  <!-- Loading Spinner -->
                  <div v-if="isLoading" class="absolute inset-0 rounded-full border-4 border-transparent border-t-orange-500 animate-spin"></div>
                  
                  <!-- Icon & Text -->
                  <div v-if="!isLoading" class="flex flex-col items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-20 w-20 transition-all duration-300" :class="isConnected ? 'text-emerald-500' : 'text-gray-400'" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path v-if="isConnected" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                      <path v-else stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <div class="text-center">
                      <p class="text-2xl font-bold tracking-wide uppercase" :class="isConnected ? 'text-emerald-600' : 'text-gray-500'">
                        {{ isConnected ? 'Connected' : 'Disconnected' }}
                      </p>
                      <p class="text-xs font-mono mt-1 tracking-widest" :class="isConnected ? 'text-emerald-500' : 'text-gray-400'">
                        {{ isConnected ? '● SECURE' : '○ UNPROTECTED' }}
                      </p>
                    </div>
                  </div>
                </div>
              </button>
            </div>
            
            <!-- Status Message -->
            <p class="text-sm text-gray-600 text-center max-w-md">
              {{ isConnected ? 'Your connection is secure and encrypted through WARP' : 'Click the button above to establish a secure connection' }}
            </p>
          </div>

          <!-- Info Grid - 2x3 grid -->
          <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <!-- IP Card -->
            <div class="group relative overflow-hidden backdrop-blur-md bg-white/90 border border-orange-200/60 rounded-2xl p-5 shadow-lg hover:shadow-xl hover:shadow-orange-200/50 transition-all duration-300 hover:scale-[1.02]">
              <div class="absolute -right-8 -top-8 w-32 h-32 bg-orange-200/20 rounded-full blur-2xl group-hover:bg-orange-300/30 transition-all duration-500"></div>
              <div class="relative flex items-start gap-3">
                <div class="p-2.5 bg-gradient-to-br from-orange-100 to-orange-200 rounded-xl ring-1 ring-orange-300/50 shadow-sm">
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-orange-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" />
                  </svg>
                </div>
                <div class="flex-1 min-w-0">
                  <p class="text-xs font-medium text-gray-500 mb-1">Public IP</p>
                  <p class="text-lg font-bold font-mono tracking-tight text-gray-900 truncate animate-fade-in" :key="ipAddress">{{ ipAddress }}</p>
                </div>
              </div>
            </div>

            <!-- City Card -->
            <div class="group relative overflow-hidden backdrop-blur-md bg-white/90 border border-orange-200/60 rounded-2xl p-5 shadow-lg hover:shadow-xl hover:shadow-orange-200/50 transition-all duration-300 hover:scale-[1.02]">
              <div class="absolute -right-8 -top-8 w-32 h-32 bg-orange-200/20 rounded-full blur-2xl group-hover:bg-orange-300/30 transition-all duration-500"></div>
              <div class="relative flex items-start gap-3">
                <div class="p-2.5 bg-gradient-to-br from-orange-100 to-orange-200 rounded-xl ring-1 ring-orange-300/50 shadow-sm">
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-orange-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                  </svg>
                </div>
                <div class="flex-1 min-w-0">
                  <p class="text-xs font-medium text-gray-500 mb-1">City</p>
                  <p class="text-lg font-bold text-gray-900 truncate animate-fade-in" :key="city">{{ city }}</p>
                </div>
              </div>
            </div>

            <!-- Country Card -->
            <div class="group relative overflow-hidden backdrop-blur-md bg-white/90 border border-orange-200/60 rounded-2xl p-5 shadow-lg hover:shadow-xl hover:shadow-orange-200/50 transition-all duration-300 hover:scale-[1.02]">
              <div class="absolute -right-8 -top-8 w-32 h-32 bg-orange-200/20 rounded-full blur-2xl group-hover:bg-orange-300/30 transition-all duration-500"></div>
              <div class="relative flex items-start gap-3">
                <div class="p-2.5 bg-gradient-to-br from-orange-100 to-orange-200 rounded-xl ring-1 ring-orange-300/50 shadow-sm">
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-orange-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                </div>
                <div class="flex-1 min-w-0">
                  <p class="text-xs font-medium text-gray-500 mb-1">Country</p>
                  <p class="text-lg font-bold text-gray-900 truncate animate-fade-in" :key="country">{{ country }}</p>
                </div>
              </div>
            </div>

            <!-- ISP Card -->
            <div class="group relative overflow-hidden backdrop-blur-md bg-white/90 border border-orange-200/60 rounded-2xl p-5 shadow-lg hover:shadow-xl hover:shadow-orange-200/50 transition-all duration-300 hover:scale-[1.02]">
              <div class="absolute -right-8 -top-8 w-32 h-32 bg-orange-200/20 rounded-full blur-2xl group-hover:bg-orange-300/30 transition-all duration-500"></div>
              <div class="relative flex items-start gap-3">
                <div class="p-2.5 bg-gradient-to-br from-orange-100 to-orange-200 rounded-xl ring-1 ring-orange-300/50 shadow-sm">
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-orange-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01" />
                  </svg>
                </div>
                <div class="flex-1 min-w-0">
                  <p class="text-xs font-medium text-gray-500 mb-1">ISP / Provider</p>
                  <p class="text-lg font-bold text-gray-900 truncate animate-fade-in" :key="isp">{{ isp }}</p>
                </div>
              </div>
            </div>

            <!-- Protocol Card -->
            <div class="group relative overflow-hidden backdrop-blur-md bg-white/90 border border-orange-200/60 rounded-2xl p-5 shadow-lg hover:shadow-xl hover:shadow-orange-200/50 transition-all duration-300 hover:scale-[1.02]">
              <div class="absolute -right-8 -top-8 w-32 h-32 bg-orange-200/20 rounded-full blur-2xl group-hover:bg-orange-300/30 transition-all duration-500"></div>
              <div class="relative flex items-start gap-3">
                <div class="p-2.5 bg-gradient-to-br from-orange-100 to-orange-200 rounded-xl ring-1 ring-orange-300/50 shadow-sm">
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-orange-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                  </svg>
                </div>
                <div class="flex-1 min-w-0">
                  <p class="text-xs font-medium text-gray-500 mb-1">Protocol</p>
                  <p class="text-lg font-bold text-gray-900 truncate animate-fade-in" :key="protocol">{{ protocol }}</p>
                </div>
              </div>
            </div>


          </div>

          <!-- Proxy Address Card - Large -->
          <div class="group relative overflow-hidden backdrop-blur-md bg-white/90 border-2 border-orange-300/70 rounded-2xl p-6 shadow-xl hover:shadow-2xl hover:shadow-orange-300/40 transition-all duration-300 mb-6">
            <div class="absolute -right-12 -top-12 w-40 h-40 bg-orange-200/30 rounded-full blur-3xl group-hover:bg-orange-300/40 transition-all duration-500"></div>
            <div class="relative">
              <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-3">
                  <div class="p-3 bg-gradient-to-br from-orange-400 to-orange-500 rounded-xl shadow-lg shadow-orange-500/30">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-7 w-7 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                  </div>
                  <div>
                    <p class="text-sm font-medium text-gray-500">Proxy Connection</p>
                    <p class="text-xs text-gray-400">SOCKS5 Proxy Address</p>
                  </div>
                </div>
                <button 
                  @click="copyToClipboard(proxyAddress)"
                  class="px-4 py-2 bg-orange-100 hover:bg-orange-200 text-orange-700 rounded-lg text-sm font-medium transition-all duration-200 flex items-center gap-2"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                  </svg>
                  Copy
                </button>
              </div>
              <div class="bg-gray-50 rounded-xl p-4 border border-gray-200">
                <p class="text-2xl font-bold font-mono text-gray-900 tracking-tight break-all animate-fade-in" :key="proxyAddress">{{ proxyAddress }}</p>
              </div>
            </div>
          </div>

          <!-- Custom Endpoint Input -->
          <div class="flex flex-col items-center gap-3 w-full max-w-md mx-auto">
            <div class="relative flex items-center w-full group">
              <div class="absolute inset-0 bg-gradient-to-r from-orange-200 to-orange-100 rounded-xl blur opacity-25 group-hover:opacity-40 transition-opacity duration-300"></div>
              <input 
                v-model="customEndpoint" 
                type="text" 
                placeholder="Custom Endpoint (e.g. 162.159.192.1:2408)" 
                class="relative w-full px-4 py-3 pr-24 rounded-xl bg-white/90 border border-orange-200 focus:border-orange-400 focus:ring-4 focus:ring-orange-100 outline-none transition-all shadow-sm text-sm font-mono text-gray-700 placeholder-gray-400"
                @keyup.enter="setEndpoint"
                :disabled="isSettingEndpoint || isLoading"
              />
              <button 
                @click="setEndpoint"
                :disabled="isSettingEndpoint || isLoading"
                class="absolute right-1.5 top-1.5 bottom-1.5 px-4 rounded-lg bg-gradient-to-r from-orange-500 to-orange-600 hover:from-orange-600 hover:to-orange-700 text-white text-xs font-bold transition-all shadow-md shadow-orange-500/20 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 z-10"
              >
                <span v-if="isSettingEndpoint" class="animate-spin h-3 w-3 border-2 border-white/30 border-t-white rounded-full"></span>
                <span>{{ isSettingEndpoint ? 'SETTING' : 'APPLY' }}</span>
              </button>
            </div>
            
            <p class="text-[10px] text-gray-400 text-center uppercase tracking-wider font-medium">
              Leave empty to reset • Auto-reconnects
            </p>
          </div>


          <!-- Service Logs Preview -->
          <router-link 
            to="/logs"
            class="mt-8 group relative overflow-hidden backdrop-blur-md bg-white/90 border border-orange-200/60 rounded-2xl shadow-lg hover:shadow-xl transition-all duration-300 block cursor-pointer hover:scale-[1.01]"
          >
            <div class="absolute -right-12 -top-12 w-40 h-40 bg-orange-200/20 rounded-full blur-3xl group-hover:bg-orange-300/40 transition-all duration-500"></div>
            
            <div class="relative p-6">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-3">
                  <div class="p-2.5 bg-gradient-to-br from-orange-100 to-orange-200 rounded-xl ring-1 ring-orange-300/50 shadow-sm">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-orange-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                  </div>
                  <div>
                    <h3 class="text-lg font-bold text-gray-900">Service Logs</h3>
                    <p class="text-xs text-gray-500">View real-time system activity</p>
                  </div>
                </div>
                <div class="flex items-center gap-3">
                  <div v-if="logs.length > 0" class="text-right mr-4">
                    <p class="text-2xl font-bold text-gray-900">{{ logs.length }}</p>
                    <p class="text-xs text-gray-500">Recent Logs</p>
                  </div>
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-orange-600 group-hover:translate-x-1 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6" />
                  </svg>
                </div>
              </div>
              
              <!-- Latest logs preview -->
              <div v-if="logs.length > 0" class="mt-4 bg-gray-900 rounded-xl p-4 font-mono text-xs">
                <div class="space-y-1">
                  <div 
                    v-for="(log, index) in logs.slice(-3)" 
                    :key="index"
                    class="flex gap-2 py-1 text-gray-300"
                  >
                    <span class="text-gray-500 flex-shrink-0 text-[10px]">{{ log.timestamp }}</span>
                    <span 
                      class="flex-shrink-0 font-semibold px-1.5 py-0.5 rounded text-[9px]"
                      :class="getLogLevelClass(log.level)"
                    >
                      {{ log.level }}
                    </span>
                    <span class="truncate text-[11px]">{{ log.message }}</span>
                  </div>
                </div>
                <p class="text-xs text-gray-500 mt-3 text-center">Click to view full logs →</p>
              </div>
              <div v-else class="mt-4 text-center text-gray-500 py-4">
                No logs available yet
              </div>
            </div>
          </router-link>
          
          <!-- Connect web socket manually if not connected -->
          <div v-if="!socket" class="fixed bottom-4 right-4 bg-red-500 text-white text-xs px-2 py-1 rounded shadow animate-bounce">
            WS Disconnected
          </div>

        </div>
      </main>

      <!-- Footer -->
      <footer class="px-6 py-4 backdrop-blur-md bg-white/80 border-t border-orange-200/50 shadow-sm">
        <div class="max-w-7xl mx-auto">
          <p v-if="error" class="text-center text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2 mb-3">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 inline mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {{ error }}
          </p>
          <p class="text-center text-sm text-gray-500">&copy; 2026 WarpPanel. All rights reserved.</p>
        </div>
      </footer>
      
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue';
import axios from 'axios';

const statusData = ref({
  status: 'disconnected',
  ip: '---',
  location: '---',
  city: 'Unknown',
  country: 'Unknown',
  details: {}
});
const isLoading = ref(false);
const isRotating = ref(false); // Kept for legacy if needed, but unused in template now
const isSettingEndpoint = ref(false);
const customEndpoint = ref('');
const error = ref(null);
const logs = ref([]);
let socket = null;

const isConnected = computed(() => statusData.value.status === 'connected');
const ipAddress = computed(() => statusData.value.ip);
const location = computed(() => statusData.value.location);
const city = computed(() => statusData.value.city || 'Unknown');
const country = computed(() => statusData.value.country || 'Unknown');
const isp = computed(() => statusData.value.isp || 'Cloudflare WARP');
const protocol = computed(() => statusData.value.warp_protocol || 'Unknown');

const proxyAddress = computed(() => statusData.value.proxy_address || 'socks5://127.0.0.1:1080');

const apiCall = async (method, url, data = null) => {
  try {
    error.value = null;
    const response = await axios[method](url, data);
    return response.data;
  } catch (err) {
    console.error(`API Error (${method.toUpperCase()} ${url}):`, err);
    error.value = err.response?.data?.detail || err.message || 'Operation failed';
    return null;
  }
};

const copyToClipboard = async (text) => {
  try {
    await navigator.clipboard.writeText(text);
    // 可以添加一个临时的成功提示
    const originalError = error.value;
    error.value = null;
    setTimeout(() => {
      if (!originalError) error.value = null;
    }, 2000);
  } catch (err) {
    console.error('Failed to copy:', err);
    error.value = 'Failed to copy to clipboard';
  }
};

const toggleConnection = async () => {
  isLoading.value = true;
  if (isConnected.value) {
    await apiCall('post', '/api/disconnect');
  } else {
    await apiCall('post', '/api/connect');
  }
  isLoading.value = false;
};

const rotateIP = async () => {
  // Legacy function - kept just in case or we can remove
  isRotating.value = true;
  try {
    const result = await apiCall('post', '/api/rotate');
    if (result) {
      console.log('IP rotation successful:', result);
    }
  } catch (err) {
    console.error('IP rotation failed:', err);
  } finally {
    isRotating.value = false;
  }
};

const setEndpoint = async () => {
  isSettingEndpoint.value = true;
  try {
    const result = await apiCall('post', '/api/config/endpoint', { endpoint: customEndpoint.value });
    if (result && result.success) {
      console.log('Endpoint set successfully:', result.endpoint);
      // Maybe show success checkmark?
      // Connection will reset automatically
      // Wait for re-connection?
    } else {
        // Error handled in apiCall generally if it returns null, but check result
    }
  } catch (err) {
    console.error('Set endpoint failed:', err);
  } finally {
    isSettingEndpoint.value = false;
  }
};

const backend = computed(() => statusData.value.backend || 'usque');

const switchBackend = async (newBackend) => {
  if (backend.value === newBackend) return;
  
  if (!confirm(`Switch backend to ${newBackend}? This will reconnect WARP.`)) return;
  
  isLoading.value = true;
  try {
    const result = await apiCall('post', '/api/backend/switch', { backend: newBackend });
    if (result && result.success) {
      console.log('Backend switched to:', result.backend);
      // Wait a bit for connection to stabilize
      setTimeout(() => {
        isLoading.value = false;
      }, 1000);
    } else {
      error.value = result?.warning || 'Failed to switch backend';
      isLoading.value = false;
    }
  } catch (err) {
    console.error('Switch backend failed:', err);
    error.value = 'Failed to switch backend';
    isLoading.value = false;
  }
};



const connectWebSocket = () => {
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${wsProtocol}//${window.location.host}/ws/status`;
  
  socket = new WebSocket(wsUrl);

  socket.onopen = () => {
    console.log('WebSocket connected');
    error.value = null;
    // Load initial logs
    fetchLogs();
  };

  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === 'status') {
      statusData.value = message.data;
    } else if (message.type === 'log') {
      // Add new log entry
      logs.value.push(message.data);
      // Keep only last 200 logs
      if (logs.value.length > 200) {
        logs.value.shift();
      }
    }
  };

  socket.onclose = () => {
    console.log('WebSocket disconnected. Reconnecting...');
    setTimeout(connectWebSocket, 3000);
  };

  socket.onerror = (err) => {
    console.error('WebSocket error:', err);
    socket.close();
  };
};

const fetchLogs = async () => {
  try {
    const response = await axios.get('/api/logs?limit=100');
    if (response.data && response.data.logs) {
      logs.value = response.data.logs;
    }
  } catch (err) {
    console.error('Failed to fetch logs:', err);
  }
};

const clearLogs = () => {
  logs.value = [];
};

const getLogLevelClass = (level) => {
  switch (level) {
    case 'ERROR':
      return 'bg-red-600 text-white';
    case 'WARNING':
      return 'bg-yellow-600 text-white';
    case 'INFO':
      return 'bg-blue-600 text-white';
    case 'DEBUG':
      return 'bg-gray-600 text-white';
    default:
      return 'bg-gray-500 text-white';
  }
};

onMounted(() => {
  connectWebSocket();
});

onUnmounted(() => {
  if (socket) {
    socket.close();
  }
});
</script>

<style>
/* Custom Scrollbar */
.custom-scrollbar::-webkit-scrollbar {
  width: 8px;
}

.custom-scrollbar::-webkit-scrollbar-track {
  background: rgba(0, 0, 0, 0.3);
  border-radius: 4px;
}

.custom-scrollbar::-webkit-scrollbar-thumb {
  background: rgba(249, 115, 22, 0.5);
  border-radius: 4px;
}

.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: rgba(249, 115, 22, 0.7);
}

/* Custom Animations */
@keyframes float {
  0%, 100% { 
    transform: translate(0, 0) scale(1); 
    opacity: 0.3;
  }
  50% { 
    transform: translate(30px, -30px) scale(1.1); 
    opacity: 0.5;
  }
}

@keyframes float-delayed {
  0%, 100% { 
    transform: translate(0, 0) scale(1); 
    opacity: 0.3;
  }
  50% { 
    transform: translate(-30px, 30px) scale(1.1); 
    opacity: 0.5;
  }
}

@keyframes pulse-slow {
  0%, 100% { 
    opacity: 0.2; 
    transform: scale(1);
  }
  50% { 
    opacity: 0.4; 
    transform: scale(1.05);
  }
}

@keyframes glow {
  0%, 100% { 
    opacity: 0.5;
  }
  50% { 
    opacity: 0.8;
  }
}

@keyframes fadeIn {
  from { 
    opacity: 0; 
    transform: translateY(10px);
  }
  to { 
    opacity: 1; 
    transform: translateY(0);
  }
}

.animate-float {
  animation: float 20s ease-in-out infinite;
}

.animate-float-delayed {
  animation: float-delayed 25s ease-in-out infinite;
}

.animate-pulse-slow {
  animation: pulse-slow 8s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}

.animate-glow {
  animation: glow 3s ease-in-out infinite;
}

.animate-fade-in {
  animation: fadeIn 0.6s ease-out;
}
</style>
