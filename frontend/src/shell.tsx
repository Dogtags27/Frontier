import { NavLink, Navigate, Outlet } from "react-router-dom";
import { useAuth } from "./auth";
import { ChatDock, useChat } from "./chat";
import { BrandMark, Icon, initials } from "./ui";

const STUDENT_MAIN = [
  { to: "/", label: "Desk", icon: "home" },
  { to: "/field", label: "Field", icon: "map" },
  { to: "/papers", label: "Papers", icon: "search" },
  { to: "/gaps", label: "Gaps", icon: "flag" },
];

const STUDENT_YOU = [
  { to: "/profile", label: "Profile", icon: "user" },
  { to: "/privacy", label: "Privacy", icon: "shield" },
];

const SUPERVISOR = [
  { to: "/roster", label: "Class", icon: "users" },
  { to: "/papers", label: "Papers", icon: "search" },
  { to: "/privacy", label: "Privacy", icon: "shield" },
];

function Item({ to, label, icon }: { to: string; label: string; icon: string }) {
  return (
    <NavLink to={to} end={to === "/" || to === "/roster"} className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
      <Icon name={icon} />
      {label}
    </NavLink>
  );
}

export function Splash() {
  return (
    <div className="splash" aria-label="Loading">
      <BrandMark />
    </div>
  );
}

function Frame({ supervisor }: { supervisor: boolean }) {
  const { user, signOut } = useAuth();
  const chat = useChat();
  const docked = !supervisor && chat.open;
  const name = user?.display_name || user?.email || "";

  return (
    <div className={`app ${docked ? "dock-open" : ""}`}>
      <nav className="sidebar" aria-label="Main">
        <NavLink to={supervisor ? "/roster" : "/"} className="brand">
          <BrandMark />
          <span>
            <span className="brand-name">Frontier</span>
            <span className="brand-tag">Research desk</span>
          </span>
        </NavLink>
        {supervisor ? (
          <>
            <span className="nav-label">Supervise</span>
            {SUPERVISOR.map((item) => (
              <Item key={item.to} {...item} />
            ))}
          </>
        ) : (
          <>
            <span className="nav-label">Research</span>
            {STUDENT_MAIN.map((item) => (
              <Item key={item.to} {...item} />
            ))}
            <span className="nav-label">You</span>
            {STUDENT_YOU.map((item) => (
              <Item key={item.to} {...item} />
            ))}
            <button className={`nav-link ${chat.open ? "active" : ""}`} type="button" onClick={() => chat.setOpen(!chat.open)}>
              <Icon name="chat" />
              Assistant
            </button>
          </>
        )}
        <div className="sidebar-foot">
          <div className="me">
            <span className="avatar">{initials(name)}</span>
            <div style={{ minWidth: 0 }}>
              <div className="me-name">{name}</div>
              <div className="me-role">{user?.signup_role}</div>
            </div>
          </div>
          <button className="nav-link" type="button" onClick={() => signOut()}>
            <Icon name="logout" />
            Sign out
          </button>
        </div>
      </nav>
      <main className="content">
        <Outlet />
      </main>
      {!supervisor && <ChatDock />}
      {!supervisor && !chat.open && (
        <button className="fab" type="button" title="Open the assistant" onClick={() => chat.setOpen(true)}>
          <Icon name="spark" />
        </button>
      )}
    </div>
  );
}

export function Shell() {
  const { user, ready } = useAuth();
  if (!ready) return <Splash />;
  if (!user) return <Navigate to="/signin" replace />;
  return <Frame supervisor={user.signup_role === "supervisor"} />;
}
