import { useState } from "react";
import type { ReactNode } from "react";
import { NavLink, Outlet } from "react-router";
import type { Role } from "../api/model";
import { useAuth } from "../auth/AuthContext";
import { strings } from "../strings";
import { IconAlert, IconHome, IconList, IconLogout, IconMenu, IconPlus, IconShieldCheck, IconUser } from "../ui/icons";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  roles: Role[] | "any";
}

export const navItems: NavItem[] = [
  { to: "/dashboard", label: strings.nav.dashboard, icon: <IconHome />, roles: "any" },
  { to: "/sale/new", label: strings.nav.newSale, icon: <IconPlus />, roles: ["BRANCH_USER"] },
  { to: "/enrolments", label: strings.nav.enrolments, icon: <IconList />, roles: ["BRANCH_USER", "CHECKER", "OPERATIONS", "AUDITOR"] },
  { to: "/approvals", label: strings.nav.approvals, icon: <IconShieldCheck />, roles: ["CHECKER", "OPERATIONS", "AUDITOR"] },
  { to: "/attention", label: strings.nav.attention, icon: <IconAlert />, roles: ["OPERATIONS", "AUDITOR"] },
];

export function Brand({ light = false }: { light?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className={`flex h-8 w-8 items-center justify-center rounded-md ${light ? "bg-white/15 text-white" : "bg-brand-600 text-white"}`}>
        <IconShieldCheck className="h-5 w-5" />
      </span>
      <div className="leading-tight">
        <p className={`text-sm font-semibold ${light ? "text-white" : "text-slate-900"}`}>{strings.appName}</p>
        <p className={`text-[11px] ${light ? "text-brand-100" : "text-slate-500"}`}>{strings.appTagline}</p>
      </div>
    </div>
  );
}

export function SyntheticBanner() {
  return (
    <div role="note" className="bg-amber-400 px-4 py-1 text-center text-xs font-semibold text-amber-950">
      {strings.syntheticBanner}
    </div>
  );
}

export function AppLayout() {
  const { me, logout, hasRole } = useAuth();
  const [open, setOpen] = useState(false);
  if (!me) return null;
  const visible = navItems.filter((n) => n.roles === "any" || hasRole(...n.roles));
  const name = me.display_name ?? me.roll_no;

  const nav = (
    <nav aria-label={strings.nav.menu} className="flex flex-col gap-1 p-3">
      {visible.map((n) => (
        <NavLink
          key={n.to}
          to={n.to}
          onClick={() => setOpen(false)}
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
              isActive ? "bg-white/15 text-white" : "text-brand-100 hover:bg-white/10 hover:text-white"
            }`
          }
        >
          {n.icon}
          {n.label}
        </NavLink>
      ))}
    </nav>
  );

  return (
    <div className="flex min-h-screen flex-col">
      {me.environment.synthetic_data && <SyntheticBanner />}
      <div className="flex flex-1">
        <aside className="hidden w-60 shrink-0 flex-col bg-brand-900 lg:flex">
          <div className="border-b border-white/10 px-4 py-4">
            <Brand light />
          </div>
          {nav}
        </aside>
        {open && (
          <div className="fixed inset-0 z-30 lg:hidden">
            <button type="button" aria-label={strings.common.close} className="absolute inset-0 bg-slate-900/40" onClick={() => setOpen(false)} />
            <aside className="relative h-full w-64 bg-brand-900">
              <div className="border-b border-white/10 px-4 py-4">
                <Brand light />
              </div>
              {nav}
            </aside>
          </div>
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 items-center justify-between gap-3 border-b border-slate-200 bg-white px-4">
            <div className="flex items-center gap-2">
              <button type="button" className="btn-ghost px-2 lg:hidden" aria-label={strings.nav.menu} onClick={() => setOpen(true)}>
                <IconMenu />
              </button>
              <div className="lg:hidden">
                <Brand />
              </div>
            </div>
            <div className="flex items-center gap-4">
              <div className="hidden text-right text-xs sm:block">
                <p className="font-semibold text-slate-800">
                  {name} <span className="font-normal text-slate-500">({me.roll_no})</span>
                </p>
                <p className="text-slate-500">
                  {strings.nav.branch} {me.branch.code}
                  {me.branch.name ? ` - ${me.branch.name}` : ""}
                  {me.cross_branch ? ` - ${strings.nav.allBranches}` : ""}
                  {me.roles.length > 0 && ` - ${me.roles.map((r) => strings.roles[r]).join(", ")}`}
                </p>
              </div>
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-50 text-brand-700 sm:hidden">
                <IconUser className="h-4 w-4" />
              </span>
              <button type="button" className="btn-secondary" onClick={() => void logout()}>
                <IconLogout className="h-4 w-4" />
                <span className="hidden sm:inline">{strings.nav.signOut}</span>
              </button>
            </div>
          </header>
          <main className="mx-auto w-full max-w-7xl flex-1 p-4 md:p-6">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}
