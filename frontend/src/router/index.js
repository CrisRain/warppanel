import { createRouter, createWebHistory } from 'vue-router';
import MainLayout from '../components/layout/MainLayout.vue';
import Dashboard from '../views/Dashboard.vue';
import KernelManager from '../views/KernelManager.vue';
import Logs from '../views/Logs.vue';
import Settings from '../views/Settings.vue';
import Login from '../views/Login.vue';
import axios from 'axios';

const routes = [
    {
        path: '/login',
        name: 'Login',
        component: Login,
        meta: { public: true }
    },
    {
        path: '/',
        component: MainLayout,
        children: [
            {
                path: '',
                name: 'Dashboard',
                component: Dashboard
            },
            {
                path: 'kernel',
                name: 'KernelManager',
                component: KernelManager
            },
            {
                path: 'logs',
                name: 'Logs',
                component: Logs
            },
            {
                path: 'settings',
                name: 'Settings',
                component: Settings
            }
        ]
    }
];

const router = createRouter({
    history: createWebHistory(),
    routes
});

// Navigation Guard
router.beforeEach(async (to, from, next) => {
    const publicPages = ['/login'];
    const authRequired = !to.meta.public;
    const token = localStorage.getItem('auth_token');

    if (authRequired) {
        if (!token) {
            // Check if backend actually requires auth (optional optimization: call /api/auth/check)
            // For now, assume if we are on client side and no token, try checking if backend allows anonymous?
            // Actually, backend returns 401 if protected and no token.
            // But we might want to check if password is set at all.
            // For simplicity, if no token, check auth status.

            try {
                // Determine API URL
                const apiBase = import.meta.env.VITE_API_BASE_URL || '/api';
                await axios.get(`${apiBase}/auth/check`);
                // If 200, it means either no password set (admin) or we are somehow auth'd (cookie?)
                // But we use bearer token.
                // If backend has no password set, get_current_user returns "admin" freely.
                next();
            } catch (error) {
                if (error.response && (error.response.status === 401 || error.response.status === 403)) {
                    next('/login');
                } else {
                    // network error? allow or block?
                    // Blocking is safer
                    next('/login');
                }
            }
        } else {
            // Validate token
            try {
                const apiBase = import.meta.env.VITE_API_BASE_URL || '/api';
                // Set default header for this check
                await axios.get(`${apiBase}/auth/check`, {
                    headers: { Authorization: `Bearer ${token}` }
                });
                next();
            } catch (error) {
                localStorage.removeItem('auth_token');
                next('/login');
            }
        }
    } else {
        next();
    }
});

export default router;
