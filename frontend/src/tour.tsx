import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useChat } from "./chat";
import { Icon } from "./ui";

type Step = {
  target?: string;
  title: string;
  body: string;
  route?: string;
  action?: { label: string; run: (ctx: { go: (path: string) => void; ask: (text: string) => void }) => void };
};

const STEPS: Step[] = [
  {
    title: "Welcome to Frontier",
    body: "Frontier helps you read research papers, see how they connect, and spot questions nobody has answered yet. This takes about a minute and you can skip it any time.",
  },
  {
    target: "paths",
    title: "Reading paths",
    body: "Name a topic and get an ordered list of papers to read, starting from the easiest entry point. No arXiv id needed.",
    route: "/field",
    action: { label: "Try a topic", run: ({ go }) => go("/field?topic=diffusion%20models") },
  },
  {
    target: "papers",
    title: "Find papers",
    body: "Search by keyword, or paste an arXiv link. Open any paper to read it here with equations and figures intact.",
    route: "/papers",
  },
  {
    target: "gaps",
    title: "Open questions",
    body: "A research gap is something the papers you read have not answered yet. Save the promising ones here, add evidence, and drop them if the evidence says no.",
    route: "/gaps",
  },
  {
    target: "assistant",
    title: "Your assistant",
    body: "Ask in plain English. It knows what you have read and links every paper it mentions. Replies keep their links when you come back later.",
    action: { label: "Ask where to start", run: ({ ask }) => ask("Where should I start with large language models?") },
  },
  {
    target: "home",
    title: "Home keeps your place",
    body: "Your reading path, open questions, and recent activity gather on Home, so you can pick up where you left off.",
    route: "/",
  },
  {
    title: "Inside a paper",
    body: "In the reader, coloured words are tasks, methods, datasets and metrics. Hover one to see what it means and find other papers that use it. Orange underlines mark the paper's key claims.",
  },
];

const EVENT = "frontier:tour";
const key = (userId: string) => `frontier.tour.${userId}`;

export function startTour() {
  window.dispatchEvent(new Event(EVENT));
}

type Box = { left: number; top: number; width: number; height: number };

export function Tour({ userId }: { userId: string }) {
  const [step, setStep] = useState<number | null>(null);
  const [box, setBox] = useState<Box | null>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const chat = useChat();

  const finish = useCallback(() => {
    localStorage.setItem(key(userId), "done");
    setStep(null);
    setBox(null);
  }, [userId]);

  useEffect(() => {
    const open = () => setStep(0);
    window.addEventListener(EVENT, open);
    return () => window.removeEventListener(EVENT, open);
  }, []);

  useEffect(() => {
    if (!userId || localStorage.getItem(key(userId))) return;
    const timer = window.setTimeout(() => setStep((current) => current ?? 0), 900);
    return () => window.clearTimeout(timer);
  }, [userId]);

  const current = step === null ? null : STEPS[step];

  const measure = useCallback(() => {
    if (!current?.target) {
      setBox(null);
      return;
    }
    const node = document.querySelector<HTMLElement>(`[data-tour="${current.target}"]`);
    const rect = node?.getBoundingClientRect();
    if (!rect || !rect.width || !rect.height) {
      setBox(null);
      return;
    }
    setBox({ left: rect.left, top: rect.top, width: rect.width, height: rect.height });
  }, [current]);

  useLayoutEffect(() => {
    measure();
  }, [measure, location.pathname]);

  useEffect(() => {
    if (step === null) return;
    window.addEventListener("resize", measure);
    const close = (event: KeyboardEvent) => event.key === "Escape" && finish();
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("keydown", close);
    };
  }, [step, measure, finish]);

  useEffect(() => {
    if (current?.route && location.pathname !== current.route) navigate(current.route);
  }, [current, location.pathname, navigate]);

  if (step === null || !current) return null;

  const last = step === STEPS.length - 1;
  const pad = 6;
  const width = 340;
  const style = box
    ? (() => {
        const roomRight = window.innerWidth - (box.left + box.width) > width + 32;
        const left = roomRight ? box.left + box.width + pad + 14 : Math.max(12, Math.min(box.left, window.innerWidth - width - 12));
        const top = roomRight ? Math.max(12, Math.min(box.top - 8, window.innerHeight - 280)) : Math.min(box.top + box.height + 16, window.innerHeight - 280);
        return { left, top, width };
      })()
    : { left: "50%", top: "50%", width, transform: "translate(-50%, -50%)" };

  return (
    <div className="tour" role="dialog" aria-modal="true" aria-label="Guided tour">
      <div className="tour-veil" onClick={finish} />
      {box ? (
        <div className="tour-spot" style={{ left: box.left - pad, top: box.top - pad, width: box.width + pad * 2, height: box.height + pad * 2 }} />
      ) : (
        <div className="tour-dim" />
      )}
      <div className="tour-card" style={style}>
        <div className="tour-dots" aria-hidden="true">
          {STEPS.map((_, index) => (
            <i key={index} className={index === step ? "on" : index < step ? "past" : ""} />
          ))}
        </div>
        <h3>{current.title}</h3>
        <p>{current.body}</p>
        {current.action && (
          <button
            className="btn accent sm tour-try"
            type="button"
            onClick={() => {
              const run = current.action!.run;
              finish();
              run({ go: (path) => navigate(path), ask: (text) => chat.ask(text) });
            }}
          >
            <Icon name="spark" />
            {current.action.label}
          </button>
        )}
        <div className="tour-foot">
          <button className="btn ghost sm" type="button" onClick={finish}>
            {last ? "Close" : "Skip tour"}
          </button>
          <div className="row">
            {step > 0 && (
              <button className="btn ghost sm" type="button" onClick={() => setStep(step - 1)}>
                Back
              </button>
            )}
            <button className="btn sm" type="button" onClick={() => (last ? finish() : setStep(step + 1))}>
              {step === 0 ? "Show me around" : last ? "Done" : "Next"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
