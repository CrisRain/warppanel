<template>
  <div class="min-h-screen flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
    <div class="max-w-md w-full space-y-8 bg-white p-10 rounded-3xl shadow-xl shadow-orange-500/5 border border-orange-100 relative overflow-hidden">
      <!-- Background Decoration -->
       <div class="absolute top-0 left-0 w-full h-full overflow-hidden pointer-events-none">
          <div class="absolute -top-[50%] -left-[50%] w-[200%] h-[200%] bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] from-orange-50/50 via-transparent to-transparent opacity-50"></div>
       </div>

      <div class="relative z-10">
        <div class="flex justify-center mb-6">
           <div class="w-16 h-16 rounded-2xl bg-orange-50 flex items-center justify-center text-orange-600">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-8 h-8">
                <!-- Lock Icon -->
                <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
              </svg>
           </div>
        </div>
        
        <h2 class="mt-2 text-center text-3xl font-bold text-gray-900 tracking-tight">
          Welcome Back
        </h2>
        <p class="mt-2 text-center text-sm text-gray-500">
          Please enter your password to continue
        </p>
      </div>

      <form class="mt-8 space-y-6 relative z-10" @submit.prevent="handleLogin">
        <div class="space-y-4">
          <div>
            <label for="password" class="sr-only">Password</label>
            <input 
              id="password" 
              name="password" 
              type="password" 
              required 
              v-model="password"
              class="appearance-none relative block w-full px-4 py-3 border border-gray-200 placeholder-gray-400 text-gray-900 rounded-xl focus:outline-none focus:ring-2 focus:ring-orange-100 focus:border-orange-500 focus:z-10 sm:text-sm transition-all bg-gray-50"
              placeholder="Enter your password"
            >
          </div>
        </div>

        <div v-if="error" class="text-red-500 text-sm text-center bg-red-50 p-2 rounded-lg border border-red-100">
            {{ error }}
        </div>

        <div>
          <button type="submit" 
            :disabled="loading"
            class="group relative w-full flex justify-center py-3 px-4 border border-transparent text-sm font-bold rounded-xl text-white bg-orange-600 hover:bg-orange-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-orange-500 disabled:opacity-50 transition-all duration-200 shadow-lg shadow-orange-500/20"
          >
            {{ loading ? 'Unlocking...' : 'Unlock Panel' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import axios from 'axios';

const router = useRouter();
const password = ref('');
const error = ref('');
const loading = ref(false);

const handleLogin = async () => {
    loading.value = true;
    error.value = '';
    
    try {
        // Use relative path for API, assuming proxy or same origin
        // Ideally we should use the configured API base URL if any
        const apiBase = import.meta.env.VITE_API_BASE_URL || '/api';
        
        const response = await axios.post(`${apiBase}/auth/login`, {
            password: password.value
        });
        
        if (response.data.success) {
            localStorage.setItem('auth_token', response.data.token);
            router.push('/');
        }
    } catch (err) {
        if (err.response && err.response.status === 401) {
            error.value = 'Invalid password';
        } else {
            error.value = 'Login failed: ' + (err.message || 'Unknown error');
        }
    } finally {
        loading.value = false;
    }
};
</script>
