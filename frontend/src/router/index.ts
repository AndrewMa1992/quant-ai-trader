import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('../views/Dashboard.vue'),
  },
  {
    path: '/factors',
    name: 'FactorResearch',
    component: () => import('../views/FactorResearch.vue'),
  },
  {
    path: '/models',
    name: 'ModelCenter',
    component: () => import('../views/ModelCenter.vue'),
  },
  {
    path: '/risk',
    name: 'RiskDashboard',
    component: () => import('../views/RiskDashboard.vue'),
  },
  {
    path: '/portfolio',
    name: 'PortfolioOptimizer',
    component: () => import('../views/PortfolioOptimizer.vue'),
  },
  {
    path: '/backtest',
    name: 'BacktestAnalysis',
    component: () => import('../views/BacktestAnalysis.vue'),
  },
  {
    path: '/execution',
    name: 'ExecutionMonitor',
    component: () => import('../views/ExecutionMonitor.vue'),
  },
  {
    path: '/orders',
    name: 'OrderHistory',
    component: () => import('../views/OrderHistory.vue'),
  },
  {
    path: '/data',
    name: 'DataExplorer',
    component: () => import('../views/DataExplorer.vue'),
  },
  {
    path: '/sync',
    name: 'DataSyncDashboard',
    component: () => import('../views/DataSyncDashboard.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
