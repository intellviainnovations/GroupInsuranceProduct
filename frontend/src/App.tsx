import { Navigate, Route, Routes } from "react-router";
import { NotFound } from "./pages/NotFound";
import { SignIn } from "./pages/SignIn";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/sign-in" replace />} />
      <Route path="/sign-in" element={<SignIn />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
