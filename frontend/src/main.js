import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import router from './router'
import axios from 'axios';

// Configure Axios Global Interceptor
axios.interceptors.request.use(config => {
    const token = localStorage.getItem('auth_token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

axios.interceptors.response.use(
    response => response,
    error => {
        if (error.response && (error.response.status === 401 || error.response.status === 403)) {
            // Redirect to login if unauthorized
            // Only redirect if not already there to avoid loops if login API itself 401s (handled in Login.vue)
            if (router.currentRoute.value.path !== '/login') {
                localStorage.removeItem('auth_token');
                router.push('/login');
            }
        }
        return Promise.reject(error);
    }
);

createApp(App).use(router).mount('#app')
