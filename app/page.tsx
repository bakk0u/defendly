"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

type User = { id: number; email: string; name: string; preferred_provider: string };
type Provider = { id: string; label: string; model: string; available: boolean; local: boolean };
type Project = { name: string; description: string; technologies: string[]; metrics: string[]; claims: string[] };
type RiskyClaim = { claim: string; risk: "low" | "medium" | "high"; reason: string; prepare: string };
type Extraction = {
  candidate_name: string; headline: string; projects: Project[]; technical_skills: string[];
  tools_frameworks: string[]; metrics: string[]; risky_claims: RiskyClaim[];
  work_experience: { company: string; role: string; period: string; achievements: string[]; technologies: string[] }[];
  education: { institution: string; degree: string; field: string; period: string; details: string[] }[];
};
type Question = { id: number; cv_id: number; item_type: string; item_name: string; question: string; focus: string; difficulty: string };
type CVResponse = { cv_id: number; source_name: string; extraction: Extraction; questions: Question[]; model_used: string };
type CVSummary = { cv_id: number; source_name: string; candidate_name: string; headline: string; project_count: number; question_count: number; created_at: string };
type Evaluation = {
  label: "Weak" | "Okay" | "Strong"; score: number; summary: string; criteria: Record<string, number>;
  missing_points: string[]; concepts_to_revise: string[]; improved_answer: string; concept_coverage: number; confidence: number;
};
type Dashboard = { total_questions: number; answered: number; average_score: number; readiness_score: number; areas: { item_name: string; item_type: string; mastery: number; confidence: number; answered: number; total: number; readiness: string }[] };
type ChatMessage = { role: "coach" | "user" | "status"; content: string; evaluation?: Evaluation };

const configuredApi = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const API_URL = configuredApi.startsWith("http") ? configuredApi.replace(/\/$/, "") : `https://${configuredApi.replace(/\/$/, "")}`;
const demoCV = `Maya Chen
Computer Science student | AI and Backend Engineering

PROJECTS
StudySync AI - Built a retrieval-augmented study assistant using Python, FastAPI, React, PostgreSQL and Ollama. Designed chunking and citation logic, evaluated 120 answers, and improved grounded-answer accuracy by 18%.
Campus Energy Dashboard - Developed a React and TypeScript dashboard that processed 50,000+ sensor records. Reduced report preparation time by 35% using Pandas and Power BI.

EXPERIENCE
Software Engineering Intern | Northstar Labs | Jun 2025 - Sep 2025
Implemented three REST API endpoints in FastAPI and added automated tests with GitHub Actions. Collaborated with four engineers through code reviews and weekly demos.

EDUCATION
B.Sc. Computer Science | Technical University | 2023 - 2026

TECHNICAL SKILLS
Python, TypeScript, React, FastAPI, SQL, PostgreSQL, Docker, Git, Pandas, Ollama`;

function Mark() { return <span className="brand-mark">D</span>; }
function initials(name: string) { return name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase(); }

export default function Home() {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState("");
  const [sessionLoading, setSessionLoading] = useState(true);
  const [authMode, setAuthMode] = useState<"login" | "register">("register");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [selectedProvider, setSelectedProvider] = useState("fallback");
  const [cvHistory, setCvHistory] = useState<CVSummary[]>([]);
  const [cvText, setCvText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [data, setData] = useState<CVResponse | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [active, setActive] = useState<"overview" | "practice" | "live" | "claims">("overview");
  const [questionIndex, setQuestionIndex] = useState(0);
  const [answer, setAnswer] = useState("");
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [liveQuestion, setLiveQuestion] = useState<Question | null>(null);
  const [liveAnswer, setLiveAnswer] = useState("");
  const [liveConnected, setLiveConnected] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);

  const authHeaders = useMemo(() => token ? { Authorization: `Bearer ${token}` } : {}, [token]);
  const currentQuestion = data?.questions[questionIndex];
  const provider = providers.find((item) => item.id === selectedProvider);

  async function api(path: string, options: RequestInit = {}) {
    return fetch(`${API_URL}${path}`, { ...options, credentials: "include", headers: { ...authHeaders, ...(options.headers || {}) } });
  }

  useEffect(() => {
    fetch(`${API_URL}/api/auth/session`, { credentials: "include" })
      .then(async (response) => {
        if (!response.ok) throw new Error();
        const payload = await response.json();
        setUser(payload.user); setToken(payload.access_token); setSelectedProvider(payload.user.preferred_provider);
      })
      .catch(() => undefined).finally(() => setSessionLoading(false));
  }, []);

  useEffect(() => {
    if (!user || !token) return;
    Promise.all([api("/api/providers"), api("/api/cvs")]).then(async ([providerResponse, cvResponse]) => {
      if (providerResponse.ok) {
        const availableProviders: Provider[] = await providerResponse.json();
        setProviders(availableProviders);
        if (!availableProviders.some((item) => item.id === selectedProvider && item.available)) setSelectedProvider(availableProviders.find((item) => item.id === "fallback")?.id || availableProviders.find((item) => item.available)?.id || "fallback");
      }
      if (cvResponse.ok) setCvHistory(await cvResponse.json());
    });
  }, [user, token]);

  useEffect(() => { transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: "smooth" }); }, [messages]);

  useEffect(() => {
    if (active !== "live" || !data || !token) return;
    const wsBase = API_URL.replace(/^http/, "ws");
    const socket = new WebSocket(`${wsBase}/ws/interview/${data.cv_id}?provider=${encodeURIComponent(selectedProvider)}`);
    socketRef.current = socket; setMessages([]); setLiveQuestion(null);
    socket.onopen = () => setLiveConnected(true);
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (payload.type === "question") { setLiveQuestion(payload.question); setMessages((current) => [...current, { role: "coach", content: payload.question.question }]); }
      else if (payload.type === "status") setMessages((current) => [...current.filter((item) => item.role !== "status"), { role: "status", content: payload.message }]);
      else if (payload.type === "evaluation") { setMessages((current) => [...current.filter((item) => item.role !== "status"), { role: "coach", content: payload.evaluation.summary, evaluation: payload.evaluation }]); refreshDashboard(data.cv_id); }
      else if (payload.type === "error") setError(payload.message);
    };
    socket.onclose = () => setLiveConnected(false);
    return () => { socket.close(); socketRef.current = null; };
  }, [active, data?.cv_id, token, selectedProvider]);

  async function submitAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setLoading(true); setError("");
    const body = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      const response = await fetch(`${API_URL}/api/auth/${authMode}`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const payload = await response.json(); if (!response.ok) throw new Error(payload.detail || "Could not sign in.");
      setUser(payload.user); setToken(payload.access_token); setSelectedProvider(payload.user.preferred_provider);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not sign in."); } finally { setLoading(false); }
  }

  async function logout() { await api("/api/auth/logout", { method: "POST" }); socketRef.current?.close(); setUser(null); setToken(""); setData(null); setCvHistory([]); setError(""); }
  async function changeProvider(value: string) { setSelectedProvider(value); const response = await api("/api/settings/provider", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider: value }) }); if (response.ok) setUser(await response.json()); }

  async function analyze(event: FormEvent) {
    event.preventDefault(); if (!cvText.trim() && !file) return setError("Paste your CV or choose a PDF first.");
    setLoading(true); setError(""); const body = new FormData(); body.append("cv_text", cvText); body.append("provider", selectedProvider); if (file) body.append("file", file);
    try {
      const response = await api("/api/cvs/extract", { method: "POST", body }); const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "We could not analyze this CV.");
      setData(payload); setActive("overview"); setQuestionIndex(0); setEvaluation(null); setDashboard(null);
      setCvHistory((current) => [{ cv_id: payload.cv_id, source_name: payload.source_name, candidate_name: payload.extraction.candidate_name, headline: payload.extraction.headline, project_count: payload.extraction.projects.length, question_count: payload.questions.length, created_at: new Date().toISOString() }, ...current]);
      await refreshDashboard(payload.cv_id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not connect to the analysis service."); } finally { setLoading(false); }
  }

  async function openCV(cvId: number) {
    setLoading(true); setError("");
    try {
      const [cvResponse, questionResponse] = await Promise.all([api(`/api/cvs/${cvId}`), api(`/api/cvs/${cvId}/questions`)]);
      if (!cvResponse.ok || !questionResponse.ok) throw new Error("This CV could not be loaded.");
      const cv = await cvResponse.json(); const questions = await questionResponse.json(); setData({ ...cv, questions }); setActive("overview"); setEvaluation(null); setQuestionIndex(0); await refreshDashboard(cvId);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "This CV could not be loaded."); } finally { setLoading(false); }
  }

  async function refreshDashboard(cvId: number) { const response = await api(`/api/cvs/${cvId}/dashboard`); if (response.ok) setDashboard(await response.json()); }
  async function submitAnswer(event: FormEvent) {
    event.preventDefault(); if (!currentQuestion || answer.trim().length < 10) return; setLoading(true); setEvaluation(null); setError("");
    try { const response = await api("/api/evaluations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question_id: currentQuestion.id, answer, provider: selectedProvider }) }); const payload = await response.json(); if (!response.ok) throw new Error(payload.detail || "Evaluation failed."); setEvaluation(payload); if (data) await refreshDashboard(data.cv_id); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Evaluation failed."); } finally { setLoading(false); }
  }
  function nextQuestion() { if (!data) return; setQuestionIndex((index) => (index + 1) % data.questions.length); setAnswer(""); setEvaluation(null); setError(""); }
  function sendLiveAnswer(event: FormEvent) { event.preventDefault(); if (!liveAnswer.trim() || socketRef.current?.readyState !== WebSocket.OPEN) return; const content = liveAnswer.trim(); setMessages((current) => [...current, { role: "user", content }]); socketRef.current.send(JSON.stringify({ type: "answer", answer: content })); setLiveAnswer(""); }
  function nextLiveQuestion() { if (socketRef.current?.readyState === WebSocket.OPEN) socketRef.current.send(JSON.stringify({ type: "next" })); }

  if (sessionLoading) return <main className="splash"><Mark /><span>Preparing your interview room</span></main>;
  if (!user) return <main className="auth-shell">
    <section className="auth-story"><a className="brand" href="#"><Mark /><span>Defendly</span></a><div className="story-copy"><span className="overline">CV INTELLIGENCE FOR SERIOUS CANDIDATES</span><h1>Your CV got attention.<br /><em>Now defend it.</em></h1><p>Transform every project, metric, and technical claim into an adaptive interview plan that learns where you need practice.</p></div><div className="story-proof"><div><strong>5x</strong><span>questions per project</span></div><div><strong>Live</strong><span>AI interview coaching</span></div><div><strong>Local</strong><span>Ollama privacy mode</span></div></div><div className="claim-card"><span>CLAIM DETECTED</span><p>“Improved model accuracy by 18%”</p><small>Prepare the baseline, evaluation set, and your exact contribution.</small></div></section>
    <section className="auth-panel"><div className="auth-box"><span className="auth-kicker">{authMode === "register" ? "CREATE YOUR WORKSPACE" : "WELCOME BACK"}</span><h2>{authMode === "register" ? "Build interview confidence." : "Continue your preparation."}</h2><p>Your CVs, practice history, and mastery map stay connected to your account.</p><form onSubmit={submitAuth}>{authMode === "register" && <label>Full name<input name="name" required minLength={2} placeholder="Maya Chen" autoComplete="name" /></label>}<label>Email address<input name="email" type="email" required placeholder="you@example.com" autoComplete="email" /></label><label>Password<input name="password" type="password" required minLength={8} placeholder="At least 8 characters" autoComplete={authMode === "login" ? "current-password" : "new-password"} /></label>{error && <p className="error" role="alert">{error}</p>}<button className="button primary" disabled={loading}>{loading ? "One moment…" : authMode === "register" ? "Create account" : "Sign in"}<span>→</span></button></form><button className="auth-switch" onClick={() => { setAuthMode(authMode === "register" ? "login" : "register"); setError(""); }}>{authMode === "register" ? "Already have an account? Sign in" : "New to Defendly? Create an account"}</button></div></section>
  </main>;

  if (!data) return <main className="intake-shell"><header className="app-topbar"><a className="brand" href="#"><Mark /><span>Defendly</span></a><div className="top-actions"><div className="provider-control"><span className="pulse" /><select value={selectedProvider} onChange={(event) => changeProvider(event.target.value)} aria-label="AI provider">{providers.map((item) => <option key={item.id} value={item.id} disabled={!item.available}>{item.label} · {item.model}{!item.available ? " (not configured)" : ""}</option>)}</select></div><button className="avatar" title={user.email}>{initials(user.name)}</button><button className="quiet" onClick={logout}>Sign out</button></div></header><section className="intake-main"><div className="intake-copy"><span className="step-label">01 / UPLOAD EVIDENCE</span><h1>Let’s map what<br />interviewers will <em>probe.</em></h1><p>Paste your CV or upload a PDF. Defendly will identify projects, skills, metrics, fragile claims, and the exact questions each line is likely to create.</p><div className="capability-strip"><span>Structured extraction</span><span>Adaptive ML</span><span>Private provider choice</span></div></div><form className="upload-card" onSubmit={analyze}><div className="upload-tabs"><button type="button" className={!file ? "active" : ""} onClick={() => setFile(null)}>Paste text</button><button type="button" className={file ? "active" : ""} onClick={() => fileRef.current?.click()}>Upload PDF</button><span>Encrypted session</span></div>{file ? <div className="file-state"><span className="pdf-badge">PDF</span><div><strong>{file.name}</strong><small>{Math.round(file.size / 1024)} KB · ready</small></div><button type="button" onClick={() => setFile(null)}>Remove</button></div> : <textarea value={cvText} onChange={(event) => setCvText(event.target.value)} placeholder="Paste the full text of your CV here…" aria-label="CV text" />}<input hidden ref={fileRef} type="file" accept="application/pdf,.pdf" onChange={(event) => setFile(event.target.files?.[0] || null)} /><div className="upload-footer"><button type="button" onClick={() => { setCvText(demoCV); setFile(null); }}>Use example CV</button><span>{cvText.length.toLocaleString()} characters</span></div>{error && <p className="error" role="alert">{error}</p>}<button className="button primary analyze" disabled={loading}>{loading ? <><i className="spinner" />Analyzing with {provider?.label || "AI"}…</> : <>Build my interview map <span>→</span></>}</button></form></section>{cvHistory.length > 0 && <section className="history"><div><span className="step-label">YOUR WORKSPACE</span><h2>Continue a previous CV</h2></div><div className="history-list">{cvHistory.slice(0, 3).map((cv) => <button key={cv.cv_id} onClick={() => openCV(cv.cv_id)}><span className="history-initial">{initials(cv.candidate_name)}</span><span><strong>{cv.source_name}</strong><small>{cv.project_count} projects · {cv.question_count} questions</small></span><b>→</b></button>)}</div></section>}</main>;

  const extraction = data.extraction; const readiness = dashboard?.readiness_score || 0; const practiced = dashboard?.answered || 0;
  return <main className="product-shell"><aside className="sidebar"><a className="brand light" href="#"><Mark /><span>Defendly</span></a><nav>{([['overview','Command center','⌂'],['practice','Practice lab','◇'],['live','Live interview','●'],['claims','Risky claims','!']] as const).map(([id,label,icon]) => <button key={id} className={active === id ? "active" : ""} onClick={() => setActive(id)}><i>{icon}</i><span>{label}</span>{id === "claims" && extraction.risky_claims.length > 0 && <b>{extraction.risky_claims.length}</b>}</button>)}</nav><div className="sidebar-grow" /><div className="readiness-mini"><div className="mini-ring" style={{ "--score": `${readiness * 3.6}deg` } as React.CSSProperties}><span>{readiness}</span></div><div><strong>Readiness</strong><small>{practiced} answers scored</small></div></div><button className="new-analysis" onClick={() => { setData(null); setDashboard(null); }}>＋ New CV analysis</button><div className="user-tile"><span>{initials(user.name)}</span><div><strong>{user.name}</strong><small>{provider?.label || selectedProvider}</small></div><button onClick={logout}>↗</button></div></aside>
    <section className="product-main"><header className="product-header"><div><span className="breadcrumb">{data.source_name} / {active.replace("live", "live interview")}</span><h2>{active === "overview" ? `Good to see you, ${extraction.candidate_name.split(" ")[0]}.` : active === "practice" ? "Practice lab" : active === "live" ? "Live interview room" : "Claims under pressure"}</h2></div><div className="header-actions"><div className="provider-control compact"><span className="pulse" /><select value={selectedProvider} onChange={(event) => changeProvider(event.target.value)}>{providers.map((item) => <option key={item.id} value={item.id} disabled={!item.available}>{item.label} · {item.model}</option>)}</select></div><button className="button primary small" onClick={() => setActive("live")}>Start live interview <span>→</span></button></div></header>{error && <div className="global-error">{error}<button onClick={() => setError("")}>×</button></div>}
      {active === "overview" && <div className="dashboard-grid"><section className="readiness-card"><div><span className="overline">ADAPTIVE READINESS MODEL</span><h3>{readiness ? "Your signal is getting sharper." : "Your interview map is ready."}</h3><p>{dashboard?.answered ? `Based on ${dashboard.answered} scored answers and concept coverage across your CV.` : `We mapped ${data.questions.length} questions across ${extraction.projects.length} projects and ${extraction.technical_skills.length} skills.`}</p><button onClick={() => setActive("practice")}>Continue adaptive practice <span>→</span></button></div><div className="readiness-orb" style={{ "--score": `${readiness * 3.6}deg` } as React.CSSProperties}><div><strong>{readiness}</strong><span>/100</span><small>mastery</small></div></div></section><section className="metric-row"><article><span>Questions mapped</span><strong>{data.questions.length}</strong><small>Personalized to this CV</small></article><article><span>Claims at risk</span><strong>{extraction.risky_claims.length}</strong><small>{extraction.risky_claims.filter((item) => item.risk === "high").length} high-priority</small></article><article><span>Concept coverage</span><strong>{dashboard?.areas.length ? Math.round(dashboard.areas.reduce((sum, area) => sum + area.mastery, 0) / dashboard.areas.length) : 0}%</strong><small>Bayesian mastery estimate</small></article></section><section className="panel projects-panel"><div className="panel-head"><div><span className="overline">CV EVIDENCE</span><h3>Projects to defend</h3></div><small>{extraction.projects.length} extracted</small></div>{extraction.projects.map((project, index) => { const area = dashboard?.areas.find((item) => item.item_name === project.name); return <article className="project-line" key={project.name}><span className="project-index">{String(index + 1).padStart(2, "0")}</span><div><h4>{project.name}</h4><p>{project.description}</p><div className="tags">{project.technologies.slice(0, 4).map((tech) => <span key={tech}>{tech}</span>)}</div></div><div className="project-score"><strong>{area?.mastery || 0}</strong><small>mastery</small><button onClick={() => { const idx = data.questions.findIndex((question) => question.item_name === project.name); setQuestionIndex(Math.max(0, idx)); setActive("practice"); }}>Practice →</button></div></article>})}</section><section className="panel skill-panel"><div className="panel-head"><div><span className="overline">DEPTH SIGNALS</span><h3>Skills on record</h3></div></div><div className="skill-list">{extraction.technical_skills.map((skill) => { const area = dashboard?.areas.find((item) => item.item_name === skill); return <button key={skill} onClick={() => { const idx = data.questions.findIndex((question) => question.item_name === skill); setQuestionIndex(Math.max(0, idx)); setActive("practice"); }}><span>{skill}</span><i><b style={{ width: `${area?.mastery || 4}%` }} /></i><small>{area?.answered ? `${area.mastery}%` : "unscored"}</small></button>})}</div></section></div>}
      {active === "practice" && currentQuestion && <div className="practice-grid"><section className="practice-card"><div className="question-top"><div className="question-count"><span>{String(questionIndex + 1).padStart(2, "0")}</span><small>of {data.questions.length}</small></div><div className="question-pills"><span>{currentQuestion.item_type}</span><span>{currentQuestion.difficulty}</span></div></div><span className="from-label">FROM {currentQuestion.item_name}</span><h3>{currentQuestion.question}</h3><div className="focus-box"><i>◎</i><div><strong>What this tests</strong><span>{currentQuestion.focus}</span></div></div><form onSubmit={submitAnswer}><label htmlFor="answer">Your structured answer</label><textarea id="answer" value={answer} onChange={(event) => setAnswer(event.target.value)} placeholder="Context → your contribution → technical decision → challenge → measurable result" /><div className="answer-actions"><span>{answer.trim() ? answer.trim().split(/\s+/).length : 0} words</span><button className="button primary small" disabled={loading || answer.trim().length < 10}>{loading ? "Scoring evidence…" : "Evaluate answer"}<span>→</span></button></div></form></section><aside className="feedback-card">{!evaluation ? <div className="feedback-empty"><span className="coach-symbol">✦</span><h3>Your evidence coach</h3><p>We score what an interviewer can verify: technical accuracy, ownership, decisions, challenges, and results.</p><ul><li>Use “I” for your contribution</li><li>Name the trade-off, not only the tool</li><li>Connect results to a baseline</li></ul></div> : <EvaluationPanel evaluation={evaluation} onNext={nextQuestion} />}</aside></div>}
      {active === "live" && <div className="live-layout"><section className="live-stage"><div className="live-stage-head"><div><span className={liveConnected ? "live-dot on" : "live-dot"} /><strong>{liveConnected ? "LIVE SESSION" : "CONNECTING"}</strong><small>Adaptive interviewer · {provider?.label}</small></div><button onClick={nextLiveQuestion}>Skip question</button></div><div className="transcript" ref={transcriptRef}>{messages.length === 0 && <div className="connecting"><i className="spinner dark" /><span>Preparing your first question…</span></div>}{messages.map((message, index) => <div key={index} className={`chat-row ${message.role}`}><span className="chat-avatar">{message.role === "user" ? initials(user.name) : "D"}</span><div><small>{message.role === "user" ? "YOU" : message.role === "status" ? "ANALYZING" : "INTERVIEWER"}</small><p>{message.content}</p>{message.evaluation && <div className="inline-score"><strong>{message.evaluation.score}</strong><span>{message.evaluation.label} · {message.evaluation.concept_coverage}% concept coverage</span><div className="tags">{message.evaluation.concepts_to_revise.slice(0, 4).map((concept) => <em key={concept}>{concept}</em>)}</div></div>}</div></div>)}</div><form className="live-composer" onSubmit={sendLiveAnswer}><textarea value={liveAnswer} onChange={(event) => setLiveAnswer(event.target.value)} placeholder={liveQuestion ? "Answer as if you are speaking to the interviewer…" : "Waiting for the interviewer…"} disabled={!liveQuestion} /><div><span>{liveAnswer.trim() ? liveAnswer.trim().split(/\s+/).length : 0} words</span><button className="button primary small" disabled={!liveConnected || liveAnswer.trim().length < 10}>Send answer <b>↑</b></button></div></form></section><aside className="live-brief"><span className="overline">INTERVIEW BRIEF</span><h3>{liveQuestion?.item_name || "Your CV"}</h3><dl><div><dt>Question type</dt><dd>{liveQuestion?.item_type || "Adaptive"}</dd></div><div><dt>Difficulty</dt><dd>{liveQuestion?.difficulty || "Calibrating"}</dd></div><div><dt>Focus</dt><dd>{liveQuestion?.focus || "Based on your weakest area"}</dd></div></dl><div className="live-tip"><strong>Stay interview-ready</strong><p>Keep your answer between 60 and 120 seconds. Lead with context, then make ownership unmistakable.</p></div></aside></div>}
      {active === "claims" && <div className="claims-view"><div className="claims-title"><span className="overline danger">PRESSURE TEST</span><h3>Every strong claim creates a follow-up.</h3><p>Prepare the evidence behind metrics, leadership language, and broad technical statements.</p></div><div className="claims-list">{extraction.risky_claims.map((claim, index) => <article key={claim.claim}><div className="claim-no">{String(index + 1).padStart(2, "0")}</div><div className="claim-content"><div><span className={`risk ${claim.risk}`}>{claim.risk} risk</span><small>CV CLAIM</small></div><h4>“{claim.claim}”</h4><dl><div><dt>Why it will be probed</dt><dd>{claim.reason}</dd></div><div><dt>Prepare this</dt><dd>{claim.prepare}</dd></div></dl></div></article>)}</div></div>}
    </section></main>;
}

function EvaluationPanel({ evaluation, onNext }: { evaluation: Evaluation; onNext: () => void }) {
  return <div className="evaluation-panel"><div className="evaluation-score"><strong>{evaluation.score}</strong><span>/100</span><em className={evaluation.label.toLowerCase()}>{evaluation.label}</em></div><p>{evaluation.summary}</p><div className="signal-bars"><div><span>Concept coverage</span><b><i style={{ width: `${evaluation.concept_coverage}%` }} /></b><small>{evaluation.concept_coverage}%</small></div><div><span>Score confidence</span><b><i style={{ width: `${evaluation.confidence}%` }} /></b><small>{evaluation.confidence}%</small></div></div><h4>Missing evidence</h4><ul>{evaluation.missing_points.map((point) => <li key={point}>{point}</li>)}</ul><h4>Revise next</h4><div className="tags revise">{evaluation.concepts_to_revise.map((concept) => <span key={concept}>{concept}</span>)}</div><details><summary>View improved answer</summary><p>{evaluation.improved_answer}</p></details><button className="next-button" onClick={onNext}>Next adaptive question <span>→</span></button></div>;
}
