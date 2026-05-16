import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import Portfolio from '../views/Portfolio.vue'
import Strategy from '../views/Strategy.vue'
import Backtest from '../views/Backtest.vue'

const routes = [
  { path: '/', name: 'Dashboard', component: Dashboard },
  { path: '/portfolio', name: 'Portfolio', component: Portfolio },
  { path: '/strategy', name: 'Strategy', component: Strategy },
  { path: '/backtest', name: 'Backtest', component: Backtest },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
