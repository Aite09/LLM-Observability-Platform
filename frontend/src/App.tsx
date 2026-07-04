import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Dashboard } from "./pages/Dashboard";
import { DriftAlerts } from "./pages/DriftAlerts";
import { Evals } from "./pages/Evals";
import { Logs } from "./pages/Logs";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="logs" element={<Logs />} />
        <Route path="evals" element={<Evals />} />
        <Route path="drift" element={<DriftAlerts />} />
      </Route>
    </Routes>
  );
}
