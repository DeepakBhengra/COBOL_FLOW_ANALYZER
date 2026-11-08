import { NavLink } from "react-router-dom";
import Icon from "./Icon.jsx";

export default function Sidebar({ pages }) {
  return (
    <nav className="sidebar" aria-label="Main navigation">
      {pages.map((page) => (
        <NavLink
          key={page.path}
          to={page.path}
          end={page.path === "/"}
          title={page.label}
          aria-label={page.label}
          className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
        >
          <Icon name={page.icon} size={20} />
        </NavLink>
      ))}
    </nav>
  );
}
