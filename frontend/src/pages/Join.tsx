import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { errorText, post } from "../api";
import { useAuth } from "../auth";
import { useToast, useToken } from "../hooks";
import { Splash } from "../shell";
import { BrandMark, Icon } from "../ui";

const JOIN_KEY = "frontier.join";

export function Join() {
  const { code = "" } = useParams();
  const { session, user, ready } = useAuth();
  const token = useToken();
  const navigate = useNavigate();
  const notify = useToast();
  const [state, setState] = useState<"working" | "failed" | "role">("working");
  const [message, setMessage] = useState("");
  const started = useRef(false);

  useEffect(() => {
    if (!ready) return;
    if (!session) {
      sessionStorage.setItem(JOIN_KEY, code);
      navigate("/signin?mode=signup", { replace: true });
      return;
    }
    if (!user) {
      sessionStorage.setItem(JOIN_KEY, code);
      navigate("/signin", { replace: true });
      return;
    }
    if (user.signup_role !== "student") {
      setState("role");
      return;
    }
    if (started.current) return;
    started.current = true;
    post<{ name?: string }>("/orgs/join", token, { code })
      .then((joined) => {
        sessionStorage.removeItem(JOIN_KEY);
        notify(`You joined ${joined.name || "the team"}. Its instructor can now see your progress summary.`);
        navigate("/", { replace: true });
      })
      .catch((err) => {
        sessionStorage.removeItem(JOIN_KEY);
        setMessage(errorText(err));
        setState("failed");
      });
  }, [ready, session, user, token, code, navigate, notify]);

  if (state === "working") return <Splash />;

  return (
    <div className="splash" style={{ padding: "1.5rem" }}>
      <div className="card col" style={{ maxWidth: "26rem", textAlign: "center", alignItems: "center", padding: "2rem" }}>
        <BrandMark />
        <h1 className="section-title" style={{ fontSize: "1.5rem" }}>
          {state === "role" ? "Students only" : "That link did not work"}
        </h1>
        <p className="muted">
          {state === "role"
            ? "Class links are for student accounts. Sign in with a student account to join."
            : message === "not found" || !message
              ? "The class code is invalid, expired, used up, or has been replaced. Ask your supervisor for a fresh link."
              : message}
        </p>
        <Link className="btn" to="/">
          <Icon name="back" />
          Back to home
        </Link>
      </div>
    </div>
  );
}
