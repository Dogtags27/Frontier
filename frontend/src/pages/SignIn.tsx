import { useState, type FormEvent } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { errorText, post } from "../api";
import { supabase, useAuth } from "../auth";
import { BrandMark, Contours, ErrorNote, Icon } from "../ui";

const JOIN_KEY = "frontier.join";

export function SignIn() {
  const { session, user, ready, refresh, signOut } = useAuth();
  const [params, setParams] = useSearchParams();
  const [mode, setMode] = useState<"signin" | "signup">(params.get("mode") === "signup" ? "signup" : "signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<"student" | "supervisor">("student");
  const [code, setCode] = useState(() => sessionStorage.getItem(JOIN_KEY) || "");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [show, setShow] = useState(false);

  if (user) {
    const joining = sessionStorage.getItem(JOIN_KEY);
    if (user.signup_role === "student" && joining) return <Navigate to={`/join/${joining}`} replace />;
    return <Navigate to={user.signup_role === "supervisor" ? "/roster" : "/"} replace />;
  }

  const finishing = Boolean(session) && ready;
  const invited = Boolean(sessionStorage.getItem(JOIN_KEY));

  function switchMode(next: "signin" | "signup") {
    setMode(next);
    setError("");
    setNotice("");
    setParams(next === "signup" ? { mode: "signup" } : {});
  }

  async function bootstrap(token: string) {
    await post("/me/bootstrap", token, { role, display_name: name.trim() });
    const joinCode = code.trim();
    if (role === "student" && joinCode) {
      try {
        await post("/orgs/join", token, { code: joinCode });
      } catch (err) {
        setNotice(`Your account is ready, but the class code did not work: ${errorText(err)}`);
      }
    }
    sessionStorage.removeItem(JOIN_KEY);
    await refresh();
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setNotice("");
    if (!supabase) {
      setError("Sign-in is not configured. Add the Supabase URL and anon key to the frontend environment.");
      return;
    }
    setBusy(true);
    try {
      if (finishing && session) {
        await bootstrap(session.access_token);
        return;
      }
      if (mode === "signin") {
        const result = await supabase.auth.signInWithPassword({ email: email.trim(), password });
        if (result.error) setError(result.error.message);
        return;
      }
      const created = await supabase.auth.signUp({ email: email.trim(), password });
      if (created.error) {
        setError(created.error.message);
        return;
      }
      if (!created.data.session) {
        setNotice("Check your inbox to confirm your email, then sign in to finish setting up.");
        setMode("signin");
        return;
      }
      await bootstrap(created.data.session.access_token);
    } catch (err) {
      setError(errorText(err, "The account could not be opened."));
    } finally {
      setBusy(false);
    }
  }

  const showProfile = finishing || mode === "signup";

  return (
    <div className="auth">
      <section className="auth-art">
        <div className="row" style={{ position: "relative" }}>
          <BrandMark />
          <span className="brand-name" style={{ color: "#fff" }}>
            Frontier
          </span>
        </div>
        <div style={{ position: "relative" }}>
          <h2>
            Stop searching papers. <em>Start connecting ideas.</em>
          </h2>
          <p>Find relevant research, trace the evidence, uncover promising gaps, and build a reading path that moves your work forward.</p>
        </div>
        <div className="auth-points">
          <div className="auth-point">
            <Icon name="compass" />
            <span>A reading path in minutes, not months.</span>
          </div>
          <div className="auth-point">
            <Icon name="flag" />
            <span>Trace every claim back to its evidence.</span>
          </div>
          <div className="auth-point">
            <Icon name="spark" />
            <span>An assistant that remembers every paper you touched.</span>
          </div>
        </div>
        <Contours />
      </section>

      <section className="auth-form-side">
        <form className="auth-card col gap-lg" onSubmit={submit}>
          <div>
            <h1>{finishing ? "Finish setting up" : mode === "signin" ? "Welcome back" : "Create your account"}</h1>
            <p className="muted mt" style={{ marginTop: "0.4rem" }}>
              {finishing
                ? "Tell us how you will use Frontier to open your workspace."
                : mode === "signin"
                  ? "Sign in to pick up where you left off."
                  : "It takes a minute. Your private graph is created on first sign-in."}
            </p>
          </div>

          {invited && !finishing && mode === "signup" && (
            <div className="alert info">
              <Icon name="users" />
              <span>You were invited to a class. Your code is filled in below.</span>
            </div>
          )}

          {!finishing && (
            <>
              <div className="field">
                <label htmlFor="email">Email</label>
                <input id="email" className="input" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@university.edu" />
              </div>
              <div className="field">
                <label htmlFor="password">Password</label>
                <div className="input-wrap">
                  <input
                    id="password"
                    className="input"
                    style={{ paddingLeft: "0.8rem", paddingRight: "2.8rem" }}
                    type={show ? "text" : "password"}
                    autoComplete={mode === "signin" ? "current-password" : "new-password"}
                    required
                    minLength={6}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder="At least 6 characters"
                  />
                  <button className="reveal" type="button" onClick={() => setShow((value) => !value)} aria-label={show ? "Hide password" : "Show password"} aria-pressed={show}>
                    <Icon name={show ? "eyeoff" : "eye"} />
                  </button>
                </div>
              </div>
            </>
          )}

          {showProfile && (
            <>
              <div className="field">
                <label htmlFor="name">Display name</label>
                <input id="name" className="input" value={name} onChange={(event) => setName(event.target.value)} placeholder="How your class will see you" />
              </div>
              <div className="field">
                <span className="label">I am a</span>
                <div className="role-cards">
                  <button type="button" className={`role-card ${role === "student" ? "on" : ""}`} onClick={() => setRole("student")}>
                    <strong>
                      <Icon name="book" />
                      Student
                    </strong>
                    <span>Read papers, spot open questions, plan your path</span>
                  </button>
                  <button type="button" className={`role-card ${role === "supervisor" ? "on" : ""}`} onClick={() => setRole("supervisor")}>
                    <strong>
                      <Icon name="users" />
                      Supervisor
                    </strong>
                    <span>Follow your students' progress</span>
                  </button>
                </div>
              </div>
              {role === "student" && (
                <div className="field">
                  <label htmlFor="code">Class code (optional)</label>
                  <input id="code" className="input mono" value={code} onChange={(event) => setCode(event.target.value)} placeholder="Paste the code from your supervisor" />
                </div>
              )}
            </>
          )}

          <ErrorNote text={error} />
          {notice && (
            <div className="alert info">
              <Icon name="check" />
              <span>{notice}</span>
            </div>
          )}

          <button className="btn block" type="submit" disabled={busy} style={{ padding: "0.75rem" }}>
            {busy ? "Working..." : finishing ? "Open my workspace" : mode === "signin" ? "Sign in" : "Create account"}
            {!busy && <Icon name="arrow" />}
          </button>

          {finishing ? (
            <button className="link-btn small" type="button" onClick={() => signOut()}>
              Use a different account
            </button>
          ) : (
            <p className="small muted" style={{ textAlign: "center" }}>
              {mode === "signin" ? "New to Frontier? " : "Already have an account? "}
              <button className="link-btn" type="button" onClick={() => switchMode(mode === "signin" ? "signup" : "signin")}>
                {mode === "signin" ? "Create an account" : "Sign in"}
              </button>
            </p>
          )}
        </form>
      </section>
    </div>
  );
}