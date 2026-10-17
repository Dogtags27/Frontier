import { useState } from "react";
import { Link } from "react-router-dom";
import { api, errorText, post, type Invite, type Student } from "../api";
import { useAuth } from "../auth";
import { Contours, Empty, ErrorNote, Icon, PageHead, SkeletonList, initials } from "../ui";
import { copyText, useFetch, useToast, useToken } from "../hooks";

export function Roster() {
  const { user, refresh } = useAuth();
  const token = useToken();
  const notify = useToast();
  const org = user?.org_id || "";
  const invite = useFetch<Invite>(org ? `/orgs/${org}/invite` : null);
  const students = useFetch<Student[]>(org ? `/orgs/${org}/students` : null);
  const [busy, setBusy] = useState("");

  const code = invite.data;
  const link = code ? `${window.location.origin}${code.join_path}` : "";
  const list = students.data || [];

  async function copy(text: string, label: string) {
    notify((await copyText(text)) ? `${label} copied` : "Copy failed", "ok");
  }

  async function rotate() {
    if (!window.confirm("Make a new class code? The old code and link stop working immediately.")) return;
    setBusy("rotate");
    try {
      await post(`/orgs/${org}/invites`, token, {});
      notify("New class code created");
      invite.reload();
    } catch (err) {
      notify(errorText(err), "error");
    } finally {
      setBusy("");
    }
  }

  async function remove(student: Student) {
    if (!window.confirm(`Remove ${student.display_name || "this student"} from your class? You will stop seeing their progress. They can rejoin with a class code.`)) return;
    setBusy(student.id);
    try {
      await api(`/orgs/${org}/students/${student.id}`, token, { method: "DELETE" });
      notify("Student removed");
      students.reload();
    } catch (err) {
      notify(errorText(err), "error");
    } finally {
      setBusy("");
    }
  }

  if (!org) {
    return (
      <div className="page narrow">
        <PageHead eyebrow="Class" title="Setting up your class" sub="Your organisation and class code are created on first sign-in." />
        <button className="btn" type="button" onClick={() => refresh()}>
          <Icon name="refresh" />
          Check again
        </button>
      </div>
    );
  }

  return (
    <div className="page">
      <PageHead eyebrow="Class" title="Your students" sub="Share the class code or link. Each student who joins gives you a read-only summary of their research progress." />

      <div className="code-card">
        <Contours />
        <div className="row between wrap" style={{ position: "relative", alignItems: "flex-start" }}>
          <div>
            <p className="small muted">Class code</p>
            {invite.loading && !code ? <div className="skeleton" style={{ height: "2.6rem", width: "14rem", marginTop: "0.4rem", opacity: 0.4 }} /> : <div className="code-value">{code?.code || "-"}</div>}
            {code && (
              <p className="small muted" style={{ marginTop: "0.5rem" }}>
                {code.used} of {code.max_uses} uses · expires {new Date(code.expires_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
              </p>
            )}
          </div>
          <div className="row wrap">
            <button className="btn accent" type="button" disabled={!code} onClick={() => copy(code?.code || "", "Code")}>
              <Icon name="copy" />
              Copy code
            </button>
            <button className="btn ghost" type="button" disabled={!code} onClick={() => copy(link, "Join link")} style={{ background: "rgba(255,255,255,0.1)", color: "#fff", borderColor: "rgba(255,255,255,0.25)" }}>
              <Icon name="link" />
              Copy join link
            </button>
            <button className="btn ghost icon-only" type="button" title="Make a new code" disabled={busy === "rotate"} onClick={rotate} style={{ background: "rgba(255,255,255,0.1)", color: "#fff", borderColor: "rgba(255,255,255,0.25)" }}>
              <Icon name="refresh" />
            </button>
          </div>
        </div>
        {link && (
          <p className="mono small muted" style={{ marginTop: "1rem", position: "relative", wordBreak: "break-all" }}>
            {link}
          </p>
        )}
      </div>

      <ErrorNote text={invite.error || students.error} />

      <div className="section-head">
        <h2 className="section-title">
          <Icon name="users" />
          Enrolled ({list.length})
        </h2>
      </div>

      {students.loading && !students.data ? (
        <SkeletonList rows={3} h="4.5rem" />
      ) : list.length ? (
        <div className="grid-3">
          {list.map((student) => (
            <div className="card student-card interactive" key={student.id}>
              <span className="avatar">{initials(student.display_name || "?")}</span>
              <div className="grow">
                <Link to={`/roster/${student.id}`} style={{ fontWeight: 600, color: "var(--text)" }}>
                  {student.display_name || "Unnamed student"}
                </Link>
                <div className="small faint">View progress</div>
              </div>
              <button className="btn ghost sm icon-only" type="button" title="Remove from class" disabled={busy === student.id} onClick={() => remove(student)}>
                <Icon name="trash" />
              </button>
            </div>
          ))}
        </div>
      ) : (
        <Empty
          icon="users"
          title="No students yet"
          text="Send the class code or the join link above. Students can enter the code at sign-up or open the link while signed in."
          action={
            <button className="btn" type="button" onClick={() => copy(link, "Join link")} disabled={!link}>
              <Icon name="link" />
              Copy join link
            </button>
          }
        />
      )}
      <p className="small faint mt-lg">Students are not told when you open their summary.</p>
    </div>
  );
}