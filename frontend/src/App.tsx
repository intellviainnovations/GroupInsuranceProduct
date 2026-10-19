import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router";
import type { Role } from "./api/model";
import { useAuth } from "./auth/AuthContext";
import { AppLayout } from "./layout/AppLayout";
import { Approvals } from "./pages/Approvals";
import { Attention } from "./pages/Attention";
import { Dashboard } from "./pages/Dashboard";
import { EnrolmentDetail } from "./pages/EnrolmentDetail";
import { EnrolmentList } from "./pages/EnrolmentList";
import { NewSale, SaleWizard } from "./pages/NewSale";
import { NoAccess, NotFound } from "./pages/NotFound";
import { SignIn } from "./pages/SignIn";
import { Spinner } from "./ui/components";

function RequireAuth({ children }: { children: ReactNode }) {
  const { me, checking } = useAuth();
  const loc = useLocation();
  if (checking) return <Spinner />;
  if (!me) return <Navigate to="/sign-in" replace state={{ from: loc.pathname }} />;
  return <>{children}</>;
}

function RequireRole({ roles, children }: { roles: Role[] | "any"; children: ReactNode }) {
  const { me, hasRole } = useAuth();
  if (!me || me.roles.length === 0) return <NoAccess />;
  if (roles !== "any" && !hasRole(...roles)) return <NoAccess />;
  return <>{children}</>;
}

const VIEWERS: Role[] = ["BRANCH_USER", "CHECKER", "OPERATIONS", "AUDITOR"];

export function App() {
  const { sessionKey, checking } = useAuth();
  if (checking) return <Spinner />;
  return (
    // Keyed by session: signing out or in remounts every screen, dropping form state.
    <Routes key={sessionKey}>
      <Route path="/sign-in" element={<SignIn />} />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<RequireRole roles="any"><Dashboard /></RequireRole>} />
        <Route path="/enrolments" element={<RequireRole roles={VIEWERS}><EnrolmentList /></RequireRole>} />
        <Route path="/enrolments/:id" element={<RequireRole roles={VIEWERS}><EnrolmentDetail /></RequireRole>} />
        <Route path="/sale/new" element={<RequireRole roles={["BRANCH_USER"]}><NewSale /></RequireRole>} />
        <Route path="/sale/:id" element={<RequireRole roles={["BRANCH_USER"]}><SaleWizard /></RequireRole>} />
        <Route path="/approvals" element={<RequireRole roles={["CHECKER", "OPERATIONS", "AUDITOR"]}><Approvals /></RequireRole>} />
        <Route path="/attention" element={<RequireRole roles={["OPERATIONS", "AUDITOR"]}><Attention /></RequireRole>} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
