import type { CSSProperties, ReactNode } from "react";

const PATHS: Record<string, string> = {
  home: "M3 11.5 12 4l9 7.5M5.5 10v9.5h5v-6h3v6h5V10",
  map: "M9 4 3 6.5v13.5l6-2.5 6 2.5 6-2.5V4l-6 2.5L9 4Zm0 0v13.5m6-11v13.5",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm9 3-4.2-4.2",
  flag: "M5 21V4m0 1h12l-2.2 4L17 13H5",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8.5c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5",
  users: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm-6 9c.6-3.2 3-5 6-5s5.4 1.8 6 5m1-9.5a3 3 0 1 0 0-6m2.5 11c1.8.3 3.2 1.6 3.5 4",
  shield: "M12 3 5 6v5.5c0 4.2 2.9 7.8 7 9.5 4.1-1.7 7-5.3 7-9.5V6l-7-3Zm-3 9 2.2 2.2L15.5 10",
  chat: "M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v9a1.5 1.5 0 0 1-1.5 1.5H10l-4.5 4v-4h0A1.5 1.5 0 0 1 4 14.5v-9Z",
  logout: "M10 4H5.5A1.5 1.5 0 0 0 4 5.5v13A1.5 1.5 0 0 0 5.5 20H10m5-4 4-4-4-4m4 4H9",
  check: "m5 12.5 4.5 4.5L19 7.5",
  plus: "M12 5v14M5 12h14",
  copy: "M9 9h9.5a1.5 1.5 0 0 1 1.5 1.5V20a1.5 1.5 0 0 1-1.5 1.5H9A1.5 1.5 0 0 1 7.5 20v-9.5A1.5 1.5 0 0 1 9 9Zm-3.5 7H5A1.5 1.5 0 0 1 3.5 14.5V5A1.5 1.5 0 0 1 5 3.5h9.5A1.5 1.5 0 0 1 16 5v.5",
  arrow: "M5 12h14m-5-5 5 5-5 5",
  back: "M19 12H5m5-5-5 5 5 5",
  book: "M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5v-15Zm0 15A1.5 1.5 0 0 0 6.5 21H19v-3",
  spark: "m12 3 1.9 5.3L19 10l-5.1 1.7L12 17l-1.9-5.3L5 10l5.1-1.7L12 3Zm7 11 .8 2.2L22 17l-2.2.8L19 20l-.8-2.2L16 17l2.2-.8L19 14Z",
  link: "M10 14a4 4 0 0 0 5.7 0l3-3A4 4 0 0 0 13 5.3l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1-1",
  refresh: "M20 11a8 8 0 0 0-14.5-3.5L4 9m0-5v5h5M4 13a8 8 0 0 0 14.5 3.5L20 15m0 5v-5h-5",
  x: "M6 6l12 12M18 6 6 18",
  send: "M4 12 20 4l-5 16-3.5-6.5L4 12Zm7.5 1.5L20 4",
  alert: "M12 8v5m0 3.5v.01M10.3 4.2 2.9 17a2 2 0 0 0 1.7 3h14.8a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0Z",
  doc: "M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Zm6 0v5h5M9 13h6m-6 3.5h4",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-13.5V12l3 2",
  layers: "m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5m-18 4 9 5 9-5",
  trash: "M4 7h16M10 11v6m4-6v6M6 7l1 12.5A1.5 1.5 0 0 0 8.5 21h7a1.5 1.5 0 0 0 1.5-1.5L18 7M9 7V4.5A1.5 1.5 0 0 1 10.5 3h3A1.5 1.5 0 0 1 15 4.5V7",
  external: "M14 4h6v6m0-6-9 9m-3-6H6a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2v-2",
  eyeoff: "M3 3l18 18M10.6 6.2A9.8 9.8 0 0 1 12 6c6.4 0 10 6 10 6a17 17 0 0 1-3.2 3.9M6.6 7.6C3.9 9.4 2 12 2 12s3.6 7 10 7c1.7 0 3.2-.4 4.5-1.1M9.9 9.9a3 3 0 0 0 4.2 4.2",
  lock: "M7 11V8a5 5 0 0 1 10 0v3m-11.5 0h13A1.5 1.5 0 0 1 20 12.5v7a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 19.5v-7A1.5 1.5 0 0 1 5.5 11Z",
  eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
  flask: "M9 3h6m-5.5 0v6.2L4.6 18a2 2 0 0 0 1.8 3h11.2a2 2 0 0 0 1.8-3L14.5 9.2V3M7.5 15h9",
  compass: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm3.5-12.5-2 5-5 2 2-5 5-2Z",
  pulse: "M3 12h4l2.5-6 4 12 2.5-6H21",
  stop: "M7 7h10v10H7z",
};

export function Icon({ name, className = "" }: { name: keyof typeof PATHS | string; className?: string }) {
  return (
    <svg className={`icon ${className}`} viewBox="0 0 24 24" aria-hidden="true">
      <path d={PATHS[name] || PATHS.spark} />
    </svg>
  );
}

export function BrandMark({ className = "brand-mark" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="9" fill="#143037" />
      <path d="M6 23c4.5-1.2 5.6-10 10-10s5.5 6.4 10 5.2" fill="none" stroke="#e0912f" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M6 18c3.5-.6 4.6-6.5 10-6.5" fill="none" stroke="#5f8f96" strokeWidth="1.4" strokeLinecap="round" opacity="0.8" />
      <circle cx="16" cy="13" r="2.4" fill="#e0912f" />
    </svg>
  );
}

export function Contours({ className = "contours" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 400 400" fill="none" aria-hidden="true">
      {Array.from({ length: 11 }, (_, i) => {
        const r = 24 + i * 17;
        const w = 6 + i * 1.6;
        return (
          <path
            key={i}
            d={`M${200 - r} ${200 + w} C${200 - r} ${200 - r * 1.1}, ${200 + r * 0.7} ${200 - r * 1.25}, ${200 + r} ${200 - w} C${200 + r * 1.1} ${200 + r * 0.9}, ${200 - r * 0.4} ${200 + r * 1.2}, ${200 - r} ${200 + w}Z`}
            stroke={i % 4 === 0 ? "#e0912f" : "#8fb0ab"}
            strokeWidth={i % 4 === 0 ? 1.4 : 0.9}
            opacity={0.35 + (i % 3) * 0.2}
          />
        );
      })}
    </svg>
  );
}

export function PageHead({ eyebrow, title, sub, actions }: { eyebrow?: string; title: string; sub?: string; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1 className="page-title">{title}</h1>
        {sub && <p className="page-sub">{sub}</p>}
      </div>
      {actions && <div className="row wrap">{actions}</div>}
    </header>
  );
}

export function Badge({ tone, children, dot }: { tone?: string; children: ReactNode; dot?: boolean }) {
  return <span className={`badge ${tone || ""} ${dot ? "dot" : ""}`}>{children}</span>;
}

export function Stat({ label, value, note, icon, tone }: { label: string; value: ReactNode; note?: string; icon?: string; tone?: string }) {
  return (
    <div className="stat" style={tone ? ({ "--tone": tone } as CSSProperties) : undefined}>
      <div className="stat-label">
        {icon && <Icon name={icon} />}
        {label}
      </div>
      <div className="stat-value">{value}</div>
      {note && <div className="stat-note">{note}</div>}
    </div>
  );
}

export function Empty({ icon = "compass", title, text, action }: { icon?: string; title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="empty">
      <Icon name={icon} />
      <h3>{title}</h3>
      {text && <p>{text}</p>}
      {action}
    </div>
  );
}

export function Skeleton({ h = "1rem", w = "100%", className = "" }: { h?: string; w?: string; className?: string }) {
  return <div className={`skeleton ${className}`} style={{ height: h, width: w }} />;
}

export function SkeletonList({ rows = 3, h = "5rem" }: { rows?: number; h?: string }) {
  return (
    <div className="col">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} h={h} />
      ))}
    </div>
  );
}

export function ErrorNote({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div className="alert" role="alert">
      <Icon name="alert" />
      <span>{text}</span>
    </div>
  );
}

export const GAP_ORDER = ["candidate", "challenged", "alive", "adopted", "killed", "scooped"] as const;

export const GAP_COLOR: Record<string, string> = {
  candidate: "var(--candidate)",
  challenged: "var(--challenged)",
  alive: "var(--alive)",
  adopted: "var(--adopted)",
  killed: "var(--killed)",
  scooped: "var(--scooped)",
};

export const GAP_HINT: Record<string, string> = {
  candidate: "Spotted in the graph, not yet tested.",
  challenged: "The adversary is checking whether it has been done.",
  alive: "Survived the challenge. Worth pursuing.",
  adopted: "Chosen as your research direction.",
  killed: "Ruled out by the evidence.",
  scooped: "A newer paper filled this gap.",
};

export const NEXT_STATUS: Record<string, string[]> = {
  candidate: ["challenged"],
  challenged: ["alive", "killed"],
  alive: ["adopted"],
};

export function Lifecycle({ status }: { status: string }) {
  if (status === "killed" || status === "scooped") {
    return (
      <div className="lifecycle">
        {["candidate", "challenged"].map((step) => (
          <span className="lc-step done" key={step}>
            <i className="lc-dot" />
            {step}
          </span>
        ))}
        <span className="lc-bar done" />
        <span className="lc-step now">
          <i className="lc-dot" style={{ background: GAP_COLOR[status], borderColor: GAP_COLOR[status] }} />
          {status}
        </span>
      </div>
    );
  }
  const steps = ["candidate", "challenged", "alive", "adopted"];
  const at = steps.indexOf(status);
  return (
    <div className="lifecycle">
      {steps.map((step, index) => (
        <span key={step} className="row" style={{ gap: 0 }}>
          {index > 0 && <span className={`lc-bar ${index <= at ? "done" : ""}`} />}
          <span className={`lc-step ${index < at ? "done" : index === at ? "now" : ""}`}>
            <i className="lc-dot" />
            {step}
          </span>
        </span>
      ))}
    </div>
  );
}

export function GapBar({ counts }: { counts: Record<string, number> }) {
  const total = GAP_ORDER.reduce((sum, key) => sum + (counts[key] || 0), 0);
  return (
    <div className="col gap-sm">
      <div className="bar" aria-hidden="true">
        {GAP_ORDER.map((key) =>
          counts[key] ? <span key={key} className={key} style={{ width: `${(counts[key] / total) * 100}%` }} /> : null,
        )}
      </div>
      <div className="legend">
        {GAP_ORDER.map((key) => (
          <span key={key}>
            <i style={{ background: GAP_COLOR[key] }} />
            {key} {counts[key] || 0}
          </span>
        ))}
      </div>
    </div>
  );
}

export function ago(value: string | number | undefined) {
  if (!value) return "";
  const time = typeof value === "number" ? value : Date.parse(value);
  if (Number.isNaN(time)) return "";
  const diff = Date.now() - time;
  const mins = Math.round(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(time).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

export function titleCase(value: string) {
  return value.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export const EVENT_LABEL: Record<string, string> = {
  gap_opened: "Gap opened",
  challenged: "Challenged",
  alive: "Survived",
  killed: "Killed",
  adopted: "Adopted",
  scooped: "Scooped",
  decided: "Decision",
  evidence_added: "Evidence added",
  read: "Read",
};
