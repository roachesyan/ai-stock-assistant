import { createRouter, createWebHistory } from "vue-router";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/history" },
    { path: "/history", name: "history", component: () => import("../views/HistoryView.vue") },
    { path: "/today", name: "today", component: () => import("../views/TodayTradesView.vue") },
    {
      path: "/runs/:runId",
      name: "run-detail",
      component: () => import("../views/RunDetailView.vue"),
      props: true,
    },
  ],
});

export default router;
