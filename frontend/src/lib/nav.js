/**
 * Information architecture: the sidebar groups, page titles and breadcrumbs come from this one list.
 * `access`: "all" (any signed-in user), "staff" (analyst + admin) or "admin". The backend enforces the same rules;
 * hiding a link here is only a convenience.
 */
export const NAV_GROUPS = [
  {
    label: "Overview",
    items: [
      { to: "/app", label: "Dashboard", icon: "LayoutDashboard", end: true, access: "all" },
      { to: "/app/predict", label: "Live prediction", icon: "Sparkle", access: "all" },
      { to: "/app/history", label: "Prediction history", icon: "History", access: "all" },
      { to: "/app/live", label: "Live data", icon: "RadioTower", access: "all" },
    ],
  },
  {
    label: "Model intelligence",
    items: [
      { to: "/app/drift", label: "Drift monitoring", icon: "Activity", access: "staff" },
      { to: "/app/drift-analysis", label: "Data vs concept drift", icon: "Split", access: "staff" },
      { to: "/app/adaptation", label: "Adaptation & performance", icon: "RefreshCcw", access: "staff" },
      { to: "/app/drift-performance", label: "Drift performance", icon: "ChartNoAxesCombined", access: "staff" },
      { to: "/app/models", label: "Model registry", icon: "Tags", access: "staff" },
    ],
  },
  {
    label: "Data operations",
    items: [
      { to: "/app/data", label: "Data management", icon: "DatabaseZap", access: "staff" },
      { to: "/app/validation", label: "Data validation", icon: "ShieldCheck", access: "staff" },
    ],
  },
  {
    label: "System",
    items: [
      { to: "/app/system", label: "System monitoring", icon: "Gauge", access: "staff" },
      { to: "/app/simulation", label: "Simulation mode", icon: "FlaskConical", access: "staff" },
    ],
  },
  {
    label: "Administration",
    items: [
      { to: "/app/audit", label: "Audit logs", icon: "ScrollText", access: "admin" },
      { to: "/app/users", label: "Users", icon: "Users", access: "admin" },
    ],
  },
  {
    label: "Help",
    items: [{ to: "/app/how-it-works", label: "How DriftWear works", icon: "BookOpen", access: "all" }],
  },
];

export function canAccess(access, role) {
  if (access === "admin") return role === "admin";
  if (access === "staff") return role === "admin" || role === "analyst";
  return Boolean(role);
}

/** Groups with only the items this role may open; empty groups are dropped. */
export function navFor(role) {
  return NAV_GROUPS.map((g) => ({ ...g, items: g.items.filter((i) => canAccess(i.access, role)) })).filter((g) => g.items.length);
}

/** The nav entry for a path (most specific match), with its group, for titles and breadcrumbs. */
export function currentPage(pathname) {
  let best = null;
  for (const g of NAV_GROUPS) {
    for (const item of g.items) {
      const hit = item.end ? pathname === item.to || pathname === `${item.to}/` : pathname === item.to || pathname.startsWith(`${item.to}/`);
      if (hit && (!best || item.to.length > best.item.to.length)) best = { group: g.label, item };
    }
  }
  return best;
}
