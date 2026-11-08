import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Sidebar from "./components/Sidebar.jsx";
import Header from "./components/Header.jsx";
import UploadPage from "./pages/UploadPage.jsx";
import OverviewPage from "./pages/OverviewPage.jsx";
import ExplorerPage from "./pages/ExplorerPage.jsx";
import FlowPage from "./pages/FlowPage.jsx";
import FlowMapPage from "./pages/FlowMapPage.jsx";
import CopybookPage from "./pages/CopybookPage.jsx";
import ProgramLogPage from "./pages/ProgramLogPage.jsx";

const PAGES = [
  { path: "/", label: "Program Upload", icon: "home", Component: UploadPage },
  { path: "/overview", label: "Program Overview", icon: "chart", Component: OverviewPage },
  { path: "/explorer", label: "Paragraph Explorer", icon: "list", Component: ExplorerPage },
  { path: "/flow", label: "Paragraph Flow", icon: "flow", Component: FlowPage },
  { path: "/map", label: "Program Flow Map", icon: "network", Component: FlowMapPage },
  { path: "/copybooks", label: "Copybook Layout", icon: "book", Component: CopybookPage },
  { path: "/program-log", label: "Program Log", icon: "list", Component: ProgramLogPage },
];

export default function App() {
  const { pathname } = useLocation();
  const current = PAGES.find((p) => p.path === pathname) || PAGES[0];

  return (
    <div className="app-shell">
      <Sidebar pages={PAGES} />
      <main className="main">
        <Header label={current.label} />
        <Routes>
          {PAGES.map(({ path, Component }) => (
            <Route key={path} path={path} element={<Component />} />
          ))}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
