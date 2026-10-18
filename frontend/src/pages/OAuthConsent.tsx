import { useEffect, useState } from "react";
import { Navigate, useLocation, useSearchParams } from "react-router-dom";
import { errorText } from "../api";
import { supabase, useAuth } from "../auth";
import { BrandMark, ErrorNote, Icon } from "../ui";
import { NEXT_KEY } from "./SignIn";

type Request = { id: string; client: string; scope: string; redirect: string };

const SCOPE_TEXT: Record<string, string> = {
  openid: "Know who you are",
  email: "See your email address",
  profile: "See your name",
  phone: "See your phone number",
};

/** Where an MCP client (Cursor, Claude, and others) asks the signed-in student for access. */
export function OAuthConsent() {
  const { session, user, ready } = useAuth();
  const [params] = useSearchParams();
  const location = useLocation();
  const authorizationId = params.get("authorization_id") || "";
  const [request, setRequest] = useState<Request | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!supabase || !session || !user || !authorizationId) return;
    sessionStorage.removeItem(NEXT_KEY);
    let alive = true;
    supabase.auth.oauth.getAuthorizationDetails(authorizationId).then(({ data, error: failed }) => {
      if (!alive) return;
      if (failed || !data) {
        setError(failed?.message || "This request has expired. Start again from your coding tool.");
        return;
      }
      if ("authorization_id" in data) {
        setRequest({ id: data.authorization_id, client: data.client?.name || "A coding tool", scope: data.scope || "", redirect: data.redirect_uri });
      } else {
        window.location.assign(data.redirect_url);
      }
    });
    return () => {
      alive = false;
    };
  }, [session, user, authorizationId]);

  if (!ready) return null;
  if (!session) {
    sessionStorage.setItem(NEXT_KEY, `${location.pathname}${location.search}`);
    return <Navigate to="/signin" replace />;
  }
  if (!user) {
    // Signed in with Google but no Frontier account yet: finish setup, then come back here.
    sessionStorage.setItem(NEXT_KEY, `${location.pathname}${location.search}`);
    return <Navigate to="/signin" replace />;
  }

  async function decide(allow: boolean) {
    if (!supabase || !request) return;
    setBusy(true);
    setError("");
    try {
      const result = allow ? await supabase.auth.oauth.approveAuthorization(request.id) : await supabase.auth.oauth.denyAuthorization(request.id);
      if (result.error || !result.data) {
        setError(result.error?.message || "That did not go through. Try again.");
        setBusy(false);
        return;
      }
      window.location.assign(result.data.redirect_url);
    } catch (err) {
      setError(errorText(err, "That did not go through. Try again."));
      setBusy(false);
    }
  }

  const supervisor = user.signup_role !== "student";
  const scopes = (request?.scope || "").split(" ").filter(Boolean);

  return (
    <div className="auth">
      <section className="auth-form-side" style={{ gridColumn: "1 / -1" }}>
        <div className="auth-card col gap-lg">
          <div className="row">
            <BrandMark />
            <span className="brand-name">Frontier</span>
          </div>
          {!authorizationId ? (
            <ErrorNote text="This page opens from a coding tool. Add Frontier as an MCP server there and sign in when it asks." />
          ) : (
            <>
              <div>
                <h1>Connect a coding tool</h1>
                <p className="muted" style={{ marginTop: "0.4rem" }}>
                  {request ? (
                    <>
                      <strong>{request.client}</strong> wants to use Frontier's research tools as <strong>{user.email}</strong>.
                    </>
                  ) : (
                    "Checking the request..."
                  )}
                </p>
              </div>

              {supervisor && (
                <div className="alert warn">
                  <Icon name="shield" />
                  <span>The research tools are for student accounts. Sign in with a student account to connect a tool.</span>
                </div>
              )}

              {request && (
                <div className="card flat tint col gap-sm">
                  <div className="label">This lets it</div>
                  <ul className="checks">
                    <li>
                      <span className="check-dot" />
                      <span>Search papers and follow citations in the shared corpus</span>
                    </li>
                    <li>
                      <span className="check-dot" />
                      <span>Read and write your notes, gaps, and reading path</span>
                    </li>
                    {scopes.map((scope) => (
                      <li key={scope}>
                        <span className="check-dot" />
                        <span>{SCOPE_TEXT[scope] || scope}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="small faint">It cannot open your chat history. You can stop it any time by removing Frontier from that tool.</p>
                </div>
              )}

              <ErrorNote text={error} />

              {request && (
                <div className="row">
                  <button className="btn ghost grow" type="button" disabled={busy} onClick={() => void decide(false)}>
                    Cancel
                  </button>
                  <button className="btn grow" type="button" disabled={busy || supervisor} onClick={() => void decide(true)}>
                    {busy ? "Working..." : "Allow access"}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </section>
    </div>
  );
}
