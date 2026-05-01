"use client";
import { useState, useEffect, useRef } from "react";
import { Bot, Mic, MicOff, Zap, Check, X, ChevronDown, ChevronUp } from "lucide-react";
import { AgentPlan } from "@/lib/types";
import { generateAgentPlan, confirmAgentPlan, getProfile } from "@/lib/api";
import { toast } from "./Toast";

interface AIAgentPanelProps {
  onConfirmed: () => void;
}

export default function AIAgentPanel({ onConfirmed }: AIAgentPanelProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [plan, setPlan] = useState<AgentPlan | null>(null);
  const [generating, setGenerating] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [recording, setRecording] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null);
  const profileRef = useRef("");

  useEffect(() => {
    getProfile().then((r) => { profileRef.current = r.text; }).catch(() => {});
  }, []);

  function startRecording() {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const w = window as any;
    const SR = w.SpeechRecognition || w.webkitSpeechRecognition;
    if (!SR) { toast("error", "Speech recognition not supported in this browser"); return; }
    const rec = new SR();
    rec.continuous = false;
    rec.interimResults = false;
    rec.lang = "en-US";
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    rec.onresult = (e: any) => {
      const transcript = e.results[0][0].transcript;
      setQuery((q: string) => (q ? q + " " + transcript : transcript).trim());
    };
    rec.onend = () => setRecording(false);
    rec.onerror = () => { toast("error", "Microphone error"); setRecording(false); };
    recognitionRef.current = rec;
    rec.start();
    setRecording(true);
  }

  function stopRecording() {
    recognitionRef.current?.stop();
    setRecording(false);
  }

  async function handleGenerate() {
    if (!query.trim()) { toast("info", "Enter a request first"); return; }
    setGenerating(true);
    setPlan(null);
    try {
      const p = await generateAgentPlan(query.trim(), profileRef.current || undefined);
      setPlan(p);
    } catch (e: unknown) { toast("error", (e as Error).message); }
    finally { setGenerating(false); }
  }

  async function handleConfirm() {
    if (!plan) return;
    setConfirming(true);
    try {
      await confirmAgentPlan(plan);
      toast("success", "Changes applied successfully");
      setPlan(null);
      setQuery("");
      onConfirmed();
    } catch (e: unknown) { toast("error", (e as Error).message); }
    finally { setConfirming(false); }
  }

  function countChanges(p: AgentPlan) {
    return (p.events_to_create?.length || 0) + (p.events_to_modify?.length || 0) + (p.events_to_delete?.length || 0) + (p.recommendation_changes?.length || 0);
  }

  return (
    <div className="agent-panel">
      {/* Header */}
      <div className="flex items-center justify-between" style={{ marginBottom: open ? 12 : 0 }}>
        <div className="flex items-center gap-2">
          <Bot size={18} style={{ color: "var(--primary)" }} />
          <span style={{ fontWeight: 600, fontSize: 14 }}>AI Agent</span>
          {plan && (
            <span className="badge badge-blue">{countChanges(plan)} changes pending</span>
          )}
        </div>
        <button className="btn btn-ghost btn-sm" onClick={() => setOpen((o) => !o)} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          {open ? <><ChevronUp size={14} /> Collapse</> : <><ChevronDown size={14} /> Expand</>}
        </button>
      </div>

      {open && (
        <>
          <div className="agent-input-row">
            <input
              className="input"
              placeholder='e.g. "Schedule meetings with top stock clients for next Monday"'
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleGenerate(); }}
              style={{ flex: 1 }}
            />
            <button
              className={`mic-btn ${recording ? "recording" : ""}`}
              onClick={recording ? stopRecording : startRecording}
              title={recording ? "Stop recording" : "Voice input"}
            >
              {recording ? <MicOff size={15} /> : <Mic size={15} />}
            </button>
            <button className="btn btn-primary" onClick={handleGenerate} disabled={generating} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              {generating ? <><span className="spinner" /> Generating…</> : <><Zap size={14} /> Generate Plan</>}
            </button>
          </div>

          {/* Plan Preview */}
          {plan && (
            <div className="agent-preview">
              {plan.reasoning && (
                <div className="reasoning-box">
                  <strong>Reasoning:</strong> {plan.reasoning}
                </div>
              )}

              {plan.events_to_create?.length > 0 && (
                <div className="preview-section">
                  <div className="preview-title">Events to Create ({plan.events_to_create.length})</div>
                  {plan.events_to_create.map((e, i) => (
                    <div key={i} className="preview-item">
                      <strong>{e.client}</strong> — {e.title} on <strong>{e.date}</strong>
                      {e.content && <div style={{ marginTop: 4, fontStyle: "italic", fontSize: 11 }}>{e.content.slice(0, 100)}…</div>}
                    </div>
                  ))}
                </div>
              )}

              {plan.events_to_modify?.length > 0 && (
                <div className="preview-section">
                  <div className="preview-title">Events to Modify ({plan.events_to_modify.length})</div>
                  {plan.events_to_modify.map((e, i) => (
                    <div key={i} className="preview-item">
                      ID: <strong>{e.id}</strong> → {JSON.stringify(e.fields)}
                    </div>
                  ))}
                </div>
              )}

              {plan.events_to_delete?.length > 0 && (
                <div className="preview-section">
                  <div className="preview-title">Events to Delete ({plan.events_to_delete.length})</div>
                  {plan.events_to_delete.map((id, i) => (
                    <div key={i} className="preview-item" style={{ color: "var(--danger)" }}>{id}</div>
                  ))}
                </div>
              )}

              {plan.recommendation_changes?.length > 0 && (
                <div className="preview-section">
                  <div className="preview-title">Recommendation Changes ({plan.recommendation_changes.length})</div>
                  {plan.recommendation_changes.map((c, i) => (
                    <div key={i} className="preview-item">
                      <strong>{c.client}</strong>: {c.field} → <strong>{String(c.value)}</strong>
                    </div>
                  ))}
                </div>
              )}

              <div className="flex gap-2 mt-2">
                <button className="btn btn-accent" onClick={handleConfirm} disabled={confirming} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  {confirming ? <><span className="spinner" /> Applying…</> : <><Check size={14} /> Confirm & Apply</>}
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => setPlan(null)} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                  <X size={13} /> Discard
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
