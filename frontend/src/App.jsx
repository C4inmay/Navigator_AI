import { useEffect, useMemo, useRef, useState } from "react";

const API_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const BRAIN_STATES = ["UNDERSTAND", "PLAN", "OBSERVE", "ACT", "VERIFY", "RECOVER", "COMPLETE"];
const idlePlan = ["Understand user request", "Search Airbnb", "Apply user constraints", "Compare candidate listings", "Verify best candidate", "Stop before reservation or payment"].map((label) => ({ label }));
const idleConstraints = ["Destination", "Guests", "Dates", "Budget", "Preference"].map((label) => ({ label, value: "Not specified" }));

function App() {
  const [task, setTask] = useState("");
  const [run, setRun] = useState(null);
  const [runId, setRunId] = useState(null);
  const [error, setError] = useState("");
  const [voiceStatus, setVoiceStatus] = useState("idle");
  const [voiceMessage, setVoiceMessage] = useState("");
  const [page, setPage] = useState("dashboard");
  const [historyRuns, setHistoryRuns] = useState([]);
  const [historyError, setHistoryError] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [selectedHistoryRun, setSelectedHistoryRun] = useState(null);
  const recognitionRef = useRef(null);
  const capturedRef = useRef(false);
  const voiceErrorRef = useRef(false);
  const running = run?.status === "queued" || run?.status === "running";
  const plan = run?.plan ?? idlePlan;
  const constraints = run?.constraints ?? idleConstraints;
  const events = run?.events ?? [{ type: "success", message: "Navigator initialized" }, { type: "success", message: "Waiting for a user task" }];

  useEffect(() => () => recognitionRef.current?.abort(), []);

  const loadHistory = async () => {
    setHistoryLoading(true);
    setHistoryError("");
    try {
      const response = await fetch(`${API_URL}/runs`);
      if (!response.ok) throw new Error("History unavailable");
      const data = await response.json();
      if (!Array.isArray(data)) throw new Error("Malformed history");
      setHistoryRuns(data);
    } catch {
      setHistoryError("Execution history is unavailable. Please check the backend and try again.");
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => { if (page === "history") loadHistory(); }, [page]);

  useEffect(() => {
    if (!runId || !running) return undefined;
    const poll = async () => {
      try {
        const response = await fetch(`${API_URL}/runs/${runId}`);
        if (!response.ok) throw new Error("Status unavailable");
        setRun(await response.json());
      } catch {
        setError("Navigator backend is unavailable. Please check the backend and try again.");
      }
    };
    poll();
    const timer = window.setInterval(poll, 1000);
    return () => window.clearInterval(timer);
  }, [runId, running]);

  const progress = useMemo(() => {
    if (!run) return 0;
    if (run.status === "completed") return 100;
    if (run.status === "failed") return 0;
    return Math.min(88, 12 + events.length * 14);
  }, [run, events.length]);

  const startVoice = () => {
    if (voiceStatus === "listening" || voiceStatus === "processing") return;
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setVoiceStatus("unsupported");
      setVoiceMessage("Voice input is not supported in this browser. You can type your request instead.");
      return;
    }
    capturedRef.current = false;
    voiceErrorRef.current = false;
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = "en-IN";
    recognition.onstart = () => { setVoiceStatus("listening"); setVoiceMessage(""); };
    recognition.onspeechend = () => { setVoiceStatus("processing"); setVoiceMessage("Transcribing..."); recognition.stop(); };
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results).map((result) => result[0].transcript).join(" ").trim();
      capturedRef.current = true;
      if (transcript) setTask(transcript);
      setVoiceStatus("captured");
      setVoiceMessage("Voice captured. You can edit the request before running Navigator.");
    };
    recognition.onerror = (event) => {
      voiceErrorRef.current = true;
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        setVoiceStatus("denied");
        setVoiceMessage("Microphone permission was denied. You can type your task instead.");
      } else if (event.error === "no-speech") {
        setVoiceStatus("error");
        setVoiceMessage("No speech was detected. Please try again or type your request.");
      } else {
        setVoiceStatus("error");
        setVoiceMessage("Voice recognition could not complete. You can type your request instead.");
      }
    };
    recognition.onend = () => {
      recognitionRef.current = null;
      if (!capturedRef.current && !voiceErrorRef.current) {
        setVoiceStatus("idle");
        setVoiceMessage("");
      }
    };
    recognitionRef.current = recognition;
    try { recognition.start(); } catch { setVoiceStatus("error"); setVoiceMessage("Voice recognition could not start. You can type your request instead."); }
  };

  const stopVoice = () => {
    if (recognitionRef.current) {
      setVoiceStatus("processing");
      setVoiceMessage("Transcribing...");
      recognitionRef.current.stop();
    }
  };

  const runAgent = async () => {
    if (running) return;
    if (task.trim().length < 3) { setError("Please enter a task before running Navigator."); return; }
    setError("");
    try {
      const response = await fetch(`${API_URL}/run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ task: task.trim() }) });
      if (!response.ok) throw new Error("Request failed");
      const data = await response.json();
      setRun(data); setRunId(data.id);
    } catch { setError("Navigator backend is unavailable. Please check the backend and try again."); }
  };

  const openHistoryRun = async (runId) => {
    setHistoryError("");
    try {
      const response = await fetch(`${API_URL}/runs/${runId}`);
      if (!response.ok) throw new Error("Run unavailable");
      setSelectedHistoryRun(await response.json());
    } catch {
      setHistoryError("That saved run is no longer available.");
    }
  };

  const deleteHistoryRun = async (runId) => {
    if (!window.confirm("Delete this saved execution history?")) return;
    setHistoryError("");
    try {
      const response = await fetch(`${API_URL}/runs/${runId}`, { method: "DELETE" });
      if (!response.ok) throw new Error("Delete failed");
      setHistoryRuns((items) => items.filter((item) => item.run_id !== runId));
      if (selectedHistoryRun?.run_id === runId) setSelectedHistoryRun(null);
    } catch {
      setHistoryError("Could not delete that saved run. Please try again.");
    }
  };

  if (page === "history") return <HistoryPage runs={historyRuns} loading={historyLoading} error={historyError} selectedRun={selectedHistoryRun} onBack={() => { setSelectedHistoryRun(null); setPage("dashboard"); }} onSelect={openHistoryRun} onDelete={deleteHistoryRun} onCloseDetail={() => setSelectedHistoryRun(null)} onReload={loadHistory} />;

  return <div className="min-h-screen bg-[#09090b] text-white">
    <header className="border-b border-zinc-800/80 bg-zinc-950/80"><div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-5 py-5 sm:px-8"><div><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-600 font-bold">N</div><h1 className="text-2xl font-bold tracking-tight">Navigator<span className="text-indigo-400">AI</span></h1></div><p className="mt-1 ml-12 text-sm text-zinc-500">Autonomous Browser Agent</p></div><div className="flex items-center gap-3"><nav className="flex rounded-lg border border-zinc-800 bg-zinc-900 p-1 text-sm"><button className="rounded-md bg-zinc-800 px-3 py-1.5 text-zinc-100">Dashboard</button><button onClick={() => setPage("history")} className="rounded-md px-3 py-1.5 text-zinc-400 hover:text-zinc-100">Execution History</button></nav><div className="flex items-center gap-2 rounded-full border border-zinc-800 bg-zinc-900 px-4 py-2"><span className={`h-2 w-2 rounded-full ${running ? "animate-pulse bg-green-400" : "bg-zinc-500"}`} /><span className="text-sm text-zinc-400">{running ? "Agent running" : "Agent ready"}</span></div></div></div></header>
    <main className="mx-auto max-w-7xl px-5 py-8 sm:px-8"><div className="mb-8"><p className="mb-2 text-sm font-medium text-indigo-400">EIGI AI HACKATHON · TRACK 02</p><h2 className="text-3xl font-bold tracking-tight sm:text-4xl">Give Navigator a goal.<br /><span className="text-zinc-500">It operates the browser.</span></h2></div>
      <section className="mb-6 rounded-2xl border border-zinc-800 bg-zinc-900/70 p-5 sm:p-6"><div className="mb-3 flex items-center justify-between gap-4"><div><h3 className="font-semibold">Natural Language Task</h3><p className="mt-1 text-xs text-zinc-500">Type or speak the Airbnb search Navigator should accomplish.</p></div><span className="rounded-full bg-indigo-500/10 px-3 py-1 text-xs text-indigo-400">Autonomous</span></div><div className="flex flex-col gap-3 md:flex-row"><textarea value={task} onChange={(event) => setTask(event.target.value)} rows={3} placeholder="Find a highly rated Airbnb in Kathmandu for 2 guests next weekend under ₹5,000 per night." className="min-h-[92px] flex-1 resize-none rounded-xl border border-zinc-800 bg-zinc-950 p-4 text-sm leading-6 text-zinc-200 outline-none transition placeholder:text-zinc-600 focus:border-indigo-500" /><div className="flex gap-3 md:flex-col"><button type="button" onClick={voiceStatus === "listening" ? stopVoice : startVoice} disabled={running || voiceStatus === "processing"} className={`min-h-11 rounded-xl border px-4 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${voiceStatus === "listening" ? "border-red-500/60 bg-red-500/10 text-red-300" : "border-zinc-700 bg-zinc-950 text-zinc-300 hover:border-indigo-500"}`}>{voiceStatus === "listening" ? "Stop listening" : voiceStatus === "processing" ? "Transcribing..." : voiceStatus === "captured" ? "Voice captured" : "Speak"}</button><button onClick={runAgent} disabled={running} className="min-h-11 rounded-xl bg-indigo-600 px-6 font-semibold transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50">{running ? "Running..." : "Run Navigator"}</button></div></div>{voiceMessage && <p className={`mt-3 text-sm ${voiceStatus === "denied" || voiceStatus === "unsupported" || voiceStatus === "error" ? "text-amber-300" : "text-green-300"}`}>{voiceMessage}</p>}{error && <p className="mt-3 text-sm text-red-400">{error}</p>}</section>
      <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3"><StatusCard title="Current Goal" value={run?.task || "Awaiting a task"} /><StatusCard title="Current Step" value={run?.current_decision || "Ready"} highlight={running} /><div className="rounded-2xl border border-zinc-800 bg-zinc-900/70 p-5"><p className="text-xs uppercase tracking-wider text-zinc-500">Progress</p><div className="mt-4 h-2 overflow-hidden rounded-full bg-zinc-800"><div className="h-full rounded-full bg-indigo-500 transition-all duration-700" style={{ width: `${progress}%` }} /></div><p className="mt-2 text-xs text-zinc-500">{progress}% complete</p></div></div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3"><Panel title="Agent Brain" subtitle="Public execution state — never private reasoning"><Brain state={run?.state || "UNDERSTAND"} status={run?.status || "idle"} completedStates={run?.completed_states || []} /></Panel><Panel title="Current Decision" subtitle="Observable agent status"><p className="text-lg font-medium leading-7 text-zinc-100">{run?.current_decision || "Navigator is ready for a task."}</p><div className="mt-5 rounded-xl border border-indigo-500/20 bg-indigo-500/5 p-4"><p className="text-xs uppercase tracking-wider text-indigo-300">Next action</p><p className="mt-2 text-sm text-zinc-300">{run?.next_action || "Enter a task to begin."}</p></div></Panel><Panel title="Task Constraints" subtitle="Extracted only when explicitly stated"><div className="space-y-3">{constraints.map((constraint) => <div key={constraint.label} className="border-l-2 border-indigo-500/60 pl-3"><p className="text-xs font-medium uppercase tracking-wider text-zinc-500">{constraint.label}</p><p className={`mt-1 text-sm ${constraint.value === "Not specified" ? "text-zinc-500" : "text-zinc-200"}`}>{constraint.value}</p></div>)}</div></Panel></div>
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2"><Panel title="Execution Plan" subtitle="Concise, user-facing action summary"><div className="space-y-3">{plan.map((step, index) => <PlanItem key={step.label} step={step} index={index} running={running} completed={run?.status === "completed"} />)}</div></Panel><Panel title="Recovery Events" subtitle="Only public browser recovery signals from this run">{run?.recovery_events?.length ? <div className="space-y-4">{run.recovery_events.map((event, index) => <EventItem key={`${event.timestamp}-${index}`} event={event} timestamp />)}</div> : <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-950/40 p-5 text-sm text-zinc-500">No recovery events detected</div>}</Panel></div>
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2"><Panel title="Agent Execution Log" subtitle="Observe, decide, act, verify, recover"><div className="space-y-4">{events.map((event, index) => <EventItem key={`${event.timestamp || "initial"}-${index}`} event={event} />)}</div></Panel><section className="overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-900/70"><div className="flex items-center justify-between border-b border-zinc-800 px-6 py-5"><div><h3 className="font-semibold">Browser Session</h3><p className="mt-1 text-xs text-zinc-500">The live browser opens separately from this dashboard.</p></div><span className="rounded-full bg-green-500/10 px-3 py-1 text-xs text-green-400">Airbnb</span></div><div className="flex aspect-video items-center justify-center bg-zinc-950"><div className="text-center"><div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-zinc-900 text-sm font-semibold text-indigo-300">AI</div><p className="font-medium text-zinc-300">{running ? "Browser agent is active" : "Browser session ready"}</p></div></div></section></div>
      {run?.saved_to_history && <section className="mt-6 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-green-900/50 bg-green-950/20 p-5"><p className="text-sm text-green-300">Run saved to execution history</p><button onClick={() => setPage("history")} className="rounded-lg border border-green-800 px-3 py-2 text-sm text-green-200 hover:bg-green-900/30">View Run History</button></section>}{run?.result && <section className="mt-6 rounded-2xl border border-zinc-800 bg-zinc-900/70 p-6"><p className="text-xs uppercase tracking-wider text-zinc-500">Final Result</p><p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-zinc-300">{run.result}</p><p className="mt-4 text-sm text-yellow-300">Safety stop active before reservation or payment.</p></section>}{run?.error && <section className="mt-6 rounded-2xl border border-red-900/50 bg-red-950/20 p-5 text-sm text-red-300">Task could not be completed. {run.error}</section>}
      <section className="mt-6 rounded-2xl border border-yellow-900/50 bg-yellow-950/20 p-5"><div><p className="font-semibold text-yellow-400">Safety Guard Active</p><p className="mt-1 text-sm leading-6 text-zinc-400">Navigator stops before reservation, payment, final booking confirmation, or any other irreversible booking action.</p></div></section>
    </main>
  </div>;
}

function Panel({ title, subtitle, children }) { return <section className="overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-900/70"><div className="border-b border-zinc-800 px-6 py-5"><h3 className="font-semibold">{title}</h3><p className="mt-1 text-xs text-zinc-500">{subtitle}</p></div><div className="p-6">{children}</div></section>; }
function StatusCard({ title, value, highlight }) { return <div className="rounded-2xl border border-zinc-800 bg-zinc-900/70 p-5"><p className="text-xs uppercase tracking-wider text-zinc-500">{title}</p><p className={`mt-3 line-clamp-2 font-semibold ${highlight ? "text-indigo-400" : "text-zinc-200"}`}>{value}</p></div>; }
function Brain({ state, status, completedStates }) { return <div className="space-y-2">{BRAIN_STATES.map((item) => { const complete = completedStates.includes(item); const active = item === state && status !== "completed"; const failed = status === "failed" && active; return <div key={item} className="flex items-center gap-3"><span aria-label={complete ? "Complete" : failed ? "Error" : active ? "Active" : "Pending"} className={`h-2.5 w-2.5 rounded-full ${complete ? "bg-green-400" : active ? failed ? "bg-red-400" : "bg-indigo-400" : "bg-zinc-700"}`} /><span className={`text-sm font-medium ${active ? "text-indigo-200" : complete ? "text-zinc-300" : "text-zinc-600"}`}>{item}</span></div>; })}</div>; }
function PlanItem({ step, index, running, completed }) { const active = running && index === 1; const done = completed || (running && index === 0); return <div className="flex items-center gap-3"><span className={`h-2.5 w-2.5 shrink-0 rounded-full ${done ? "bg-green-400" : active ? "bg-indigo-400" : "bg-zinc-700"}`} /><span className={active ? "text-sm text-indigo-200" : done ? "text-sm text-zinc-300" : "text-sm text-zinc-500"}>{step.label}</span></div>; }
function EventItem({ event, timestamp }) { const recovery = event.type === "recovery"; const error = event.type === "error"; const safety = event.type === "safety"; const time = event.timestamp ? new Date(event.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : ""; return <div className="flex items-start gap-3">{timestamp && <span className="w-16 pt-0.5 text-xs text-zinc-600">{time}</span>}<span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${error ? "bg-red-400" : recovery || safety ? "bg-yellow-400" : "bg-green-400"}`} /><span className={`text-sm ${error ? "text-red-300" : safety ? "text-yellow-300" : "text-zinc-300"}`}>{event.message}</span></div>; }

function HistoryPage({ runs, loading, error, selectedRun, onBack, onSelect, onDelete, onCloseDetail, onReload }) {
  if (selectedRun) return <RunDetail run={selectedRun} onBack={onCloseDetail} />;
  return <div className="min-h-screen bg-[#09090b] text-white"><header className="border-b border-zinc-800/80 bg-zinc-950/80"><div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-5 py-5 sm:px-8"><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-600 font-bold">N</div><div><h1 className="text-2xl font-bold tracking-tight">Navigator<span className="text-indigo-400">AI</span></h1><p className="text-sm text-zinc-500">Autonomous Browser Agent</p></div></div><nav className="flex rounded-lg border border-zinc-800 bg-zinc-900 p-1 text-sm"><button onClick={onBack} className="rounded-md px-3 py-1.5 text-zinc-400 hover:text-zinc-100">Dashboard</button><button className="rounded-md bg-zinc-800 px-3 py-1.5 text-zinc-100">Execution History</button></nav></div></header><main className="mx-auto max-w-5xl px-5 py-8 sm:px-8"><div className="mb-7 flex flex-wrap items-end justify-between gap-4"><div><p className="text-sm font-medium text-indigo-400">LOCAL OBSERVABILITY</p><h2 className="mt-1 text-3xl font-bold">Execution History</h2><p className="mt-2 text-sm text-zinc-500">Saved locally on this computer. Newest runs appear first.</p></div><button onClick={onReload} disabled={loading} className="rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-300 hover:border-indigo-500 disabled:opacity-50">Refresh</button></div>{error && <div className="mb-5 rounded-xl border border-red-900/50 bg-red-950/20 p-4 text-sm text-red-300">{error}</div>}{loading ? <div className="rounded-2xl border border-zinc-800 bg-zinc-900/70 p-8 text-sm text-zinc-500">Loading saved executions...</div> : runs.length === 0 ? <div className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/40 p-10 text-center text-sm text-zinc-500">No executions yet. Run Navigator to create your first execution.</div> : <div className="space-y-4">{runs.map((run) => <HistoryCard key={run.run_id} run={run} onSelect={onSelect} onDelete={onDelete} />)}</div>}</main></div>;
}

function HistoryCard({ run, onSelect, onDelete }) { const completed = run.status === "completed"; return <article className="rounded-2xl border border-zinc-800 bg-zinc-900/70 p-5 sm:p-6"><div className="flex flex-col justify-between gap-4 sm:flex-row"><div><p className={`text-sm font-semibold ${completed ? "text-green-400" : "text-red-300"}`}>{completed ? "Completed" : (run.status || "Failed")}</p><h3 className="mt-2 max-w-2xl text-base font-medium text-zinc-100">{run.task || "Task not available"}</h3><p className="mt-2 text-sm text-zinc-500">{formatDate(run.started_at)} | {formatDuration(run.duration_seconds)} | {pluralize(run.recovery_count, "recovery")}</p></div><div className="flex shrink-0 items-start gap-2"><button onClick={() => onSelect(run.run_id)} className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium hover:bg-indigo-500">View Run</button><button onClick={() => onDelete(run.run_id)} className="rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-400 hover:border-red-800 hover:text-red-300">Delete</button></div></div></article>; }

function RunDetail({ run, onBack }) { const safety = run.safety || {}; const constraints = run.constraints || {}; return <div className="min-h-screen bg-[#09090b] text-white"><header className="border-b border-zinc-800/80 bg-zinc-950/80"><div className="mx-auto flex max-w-5xl items-center justify-between px-5 py-5 sm:px-8"><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-600 font-bold">N</div><h1 className="text-2xl font-bold">Navigator<span className="text-indigo-400">AI</span></h1></div><button onClick={onBack} className="rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-300 hover:border-indigo-500">Back to Execution History</button></div></header><main className="mx-auto max-w-5xl px-5 py-8 sm:px-8"><p className="text-sm font-medium text-indigo-400">NAVIGATOR RUN</p><h2 className="mt-2 text-3xl font-bold">Execution Report</h2><div className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-4"><DetailMetric label="Status" value={run.status === "completed" ? "Completed" : (run.status || "Failed")} good={run.status === "completed"} /><DetailMetric label="Duration" value={formatDuration(run.duration_seconds)} /><DetailMetric label="Recoveries" value={String(run.recovery_count ?? 0)} /><DetailMetric label="Human interventions" value={String(run.human_interventions ?? 0)} /></div><DetailSection title="User Task"><p className="whitespace-pre-wrap text-sm leading-6 text-zinc-300">{run.task || "Not available"}</p></DetailSection><DetailSection title="Agent Plan"><div className="space-y-2">{(run.plan || []).map((item, index) => <p key={`${item}-${index}`} className="text-sm text-zinc-300">{item}</p>)}</div></DetailSection><DetailSection title="Constraints"><div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{Object.entries(constraints).map(([key, value]) => <div key={key} className="rounded-lg bg-zinc-950/50 p-3"><p className="text-xs uppercase tracking-wider text-zinc-500">{key}</p><p className="mt-1 text-sm text-zinc-200">{value || "Not specified"}</p></div>)}</div></DetailSection><DetailSection title="Execution Timeline"><div className="space-y-4">{(run.events || []).length ? run.events.map((event, index) => <EventItem key={`${event.timestamp}-${index}`} event={event} timestamp />) : <p className="text-sm text-zinc-500">No event history is available.</p>}</div></DetailSection><DetailSection title="Recovery"><p className="text-sm text-zinc-300">{pluralize(run.recovery_count, "recovery event")}</p></DetailSection><DetailSection title="Final Result"><p className="whitespace-pre-wrap text-sm leading-6 text-zinc-300">{run.final_result?.summary || "Not available"}</p></DetailSection><DetailSection title="Safety"><div className="space-y-2 text-sm text-zinc-300"><p>Reservation attempted: {safety.reservation_attempted ? "YES" : "NO"}</p><p>Payment attempted: {safety.payment_attempted ? "YES" : "NO"}</p><p className={safety.safety_stop ? "text-yellow-300" : "text-zinc-500"}>Safety stop: {safety.safety_stop ? "YES" : "Not available"}</p></div></DetailSection></main></div>; }

function DetailSection({ title, children }) { return <section className="mt-6 rounded-2xl border border-zinc-800 bg-zinc-900/70 p-5"><h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">{title}</h3><div className="mt-4">{children}</div></section>; }
function DetailMetric({ label, value, good }) { return <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 p-4"><p className="text-xs uppercase tracking-wider text-zinc-500">{label}</p><p className={`mt-2 text-sm font-semibold ${good ? "text-green-400" : "text-zinc-200"}`}>{value}</p></div>; }
function formatDate(value) { if (!value) return "Date unavailable"; const date = new Date(value); return Number.isNaN(date.getTime()) ? "Date unavailable" : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" }); }
function formatDuration(seconds) { if (typeof seconds !== "number") return "Duration unavailable"; const minutes = Math.floor(seconds / 60); const remaining = seconds % 60; return minutes ? `${minutes}m ${remaining}s` : `${remaining}s`; }
function pluralize(value, noun) { const count = Number(value) || 0; return `${count} ${noun}${count === 1 ? "" : "s"}`; }

export default App;
