import { useAuth } from "../auth";
import { Icon, PageHead } from "../ui";

type Row = { icon: string; title: string; text: string; no?: boolean };

const STUDENT_SEES: Row[] = [
  { icon: "flag", title: "Gaps", text: "Open gaps with their status, score, and how much evidence backs them." },
  { icon: "book", title: "Reading", text: "Recent reads with depth and short notes, plus your current reading path." },
  { icon: "check", title: "Decisions", text: "What you decided about a gap and why, including decisions that were later invalidated." },
  { icon: "pulse", title: "Research timeline", text: "Gaps opened, challenged, killed, adopted, scooped, and papers read." },
  { icon: "layers", title: "Totals", text: "Counts of gaps, reads, decisions, and concepts you know." },
];

const STUDENT_NOT: Row[] = [
  { icon: "chat", title: "Your chats", text: "Conversations with the assistant and their tool traces stay on your private graph.", no: true },
  { icon: "lock", title: "Raw memory", text: "Facts the assistant remembers about you are never shown. You can delete them from your profile.", no: true },
  { icon: "eye", title: "Who looked", text: "You are not notified when a supervisor opens your summary, and there is no access log.", no: true },
];

const SUPERVISOR_NOT: Row[] = [
  { icon: "chat", title: "No chats", text: "You cannot open a student's conversations, traces, or raw memory.", no: true },
  { icon: "lock", title: "Read only", text: "Nothing you do can change a student's graph. The summary is served by read-only queries.", no: true },
  { icon: "users", title: "Enrolled students only", text: "Removing a student takes effect immediately on their next request.", no: true },
];

function Rows({ rows }: { rows: Row[] }) {
  return (
    <div className="privacy-list">
      {rows.map((row) => (
        <div className={`card privacy-row ${row.no ? "no" : ""}`} key={row.title}>
          <span className="ico">
            <Icon name={row.icon} />
          </span>
          <div>
            <h3>{row.title}</h3>
            <p className="muted small">{row.text}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

export function Privacy() {
  const { user } = useAuth();
  const supervisor = user?.signup_role === "supervisor";

  return (
    <div className="page narrow">
      <PageHead
        eyebrow="Privacy"
        title={supervisor ? "What you can and cannot see" : "Who sees what"}
        sub={
          supervisor
            ? "Supervisors get one progress summary per enrolled student, and nothing more."
            : "If you join a class, your supervisor sees a summary of your research progress. Here is exactly what that means."
        }
      />
      {!supervisor && (
        <>
          <h2 className="section-title" style={{ marginBottom: "0.8rem" }}>
            Your supervisor can see
          </h2>
          <Rows rows={STUDENT_SEES} />
          <h2 className="section-title" style={{ margin: "2rem 0 0.8rem" }}>
            They cannot see
          </h2>
          <Rows rows={STUDENT_NOT} />
        </>
      )}
      {supervisor && (
        <>
          <h2 className="section-title" style={{ marginBottom: "0.8rem" }}>
            Not available to you
          </h2>
          <Rows rows={SUPERVISOR_NOT} />
        </>
      )}
    </div>
  );
}
