import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import { Desk } from "./pages/Desk";
import { Field } from "./pages/Field";
import { Gaps } from "./pages/Gaps";
import { Join } from "./pages/Join";
import { Ledger } from "./pages/Ledger";
import { PaperPage } from "./pages/Paper";
import { Papers } from "./pages/Papers";
import { Privacy } from "./pages/Privacy";
import { Profile } from "./pages/Profile";
import { Roster } from "./pages/Roster";
import { SignIn } from "./pages/SignIn";
import { Shell } from "./shell";

function Only({ role, children }: { role: "student" | "supervisor"; children: ReactNode }) {
  const { user } = useAuth();
  if (!user) return null;
  if (user.signup_role !== role) return <Navigate to={role === "student" ? "/roster" : "/"} replace />;
  return <>{children}</>;
}

export function App() {
  const student = (node: ReactNode) => <Only role="student">{node}</Only>;
  const supervisor = (node: ReactNode) => <Only role="supervisor">{node}</Only>;
  return (
    <Routes>
      <Route path="/signin" element={<SignIn />} />
      <Route path="/join/:code" element={<Join />} />
      <Route element={<Shell />}>
        <Route path="/" element={student(<Desk />)} />
        <Route path="/field" element={student(<Field />)} />
        <Route path="/papers" element={<Papers />} />
        <Route path="/papers/:id" element={<PaperPage />} />
        <Route path="/gaps" element={student(<Gaps />)} />
        <Route path="/gaps/:id" element={student(<Gaps />)} />
        <Route path="/profile" element={student(<Profile />)} />
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/roster" element={supervisor(<Roster />)} />
        <Route path="/roster/:id" element={supervisor(<Ledger />)} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
