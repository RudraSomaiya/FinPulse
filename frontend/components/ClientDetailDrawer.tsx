"use client";
import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  X, ChevronLeft, ChevronRight, List, Pencil, Save, X as XIcon,
  Sparkles, TrendingUp, Bot, Mail, MessageSquare, Check, Download,
} from "lucide-react";
import { Recommendation, Reminder, CLUSTER_COLORS } from "@/lib/types";
import {
  generateMarketOutlook,
  generateClientPlan,
  sendEmailReport,
  sendWhatsAppReport,
  getLivePrice,
} from "@/lib/api";
import { toast } from "./Toast";
import RemindersList from "./RemindersList";

interface ClientDetailDrawerProps {
  date: string | null;
  dayRecs: Recommendation[];
  dayReminders: Reminder[];
  onClose: () => void;
  onRemindersChanged: () => void;
  writingProfile: string;
}

function formatSGD(v: number | null | undefined) {
  if (v == null) return "—";
  return `$${v.toLocaleString("en-SG", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

function isTopBuyer(val: unknown): boolean {
  if (typeof val === "boolean") return val;
  if (typeof val === "string") return ["true", "yes", "1"].includes(val.toLowerCase());
  if (typeof val === "number") return val === 1;
  return false;
}

export default function ClientDetailDrawer({
  date,
  dayRecs,
  dayReminders,
  onClose,
  onRemindersChanged,
  writingProfile,
}: ClientDetailDrawerProps) {
  const [idx, setIdx] = useState(0);
  const [marketOutlook, setMarketOutlook] = useState("");
  const [futurePlan, setFuturePlan] = useState("");
  const [editingMO, setEditingMO] = useState(false);
  const [editingPlan, setEditingPlan] = useState(false);
  const [editMOText, setEditMOText] = useState("");
  const [editPlanText, setEditPlanText] = useState("");
  const [generatingMO, setGeneratingMO] = useState(false);
  const [generatingPlan, setGeneratingPlan] = useState(false);
  const [livePrice, setLivePrice] = useState<{ product: string; price: number | null } | null>(null);
  const [sendingEmail, setSendingEmail] = useState(false);
  const [sendingWA, setSendingWA] = useState(false);
  const [includeMO, setIncludeMO] = useState(true);
  const [includePlan, setIncludePlan] = useState(true);
  const [showAll, setShowAll] = useState(false);

  const row = dayRecs[Math.max(0, Math.min(idx, dayRecs.length - 1))];
  const clusterColor = CLUSTER_COLORS[row?.Cluster || ""] || "#777";

  useEffect(() => {
    setIdx(0);
    setMarketOutlook("");
    setFuturePlan("");
    setLivePrice(null);
    setEditingMO(false);
    setEditingPlan(false);
  }, [date]);

  useEffect(() => {
    setLivePrice(null);
    if (!row) return;
    const prod = (row as Record<string, unknown>)["Product Name"] as string || "";
    if (!prod || prod.includes(" ")) return;
    getLivePrice(prod)
      .then((r) => setLivePrice({ product: prod, price: r.price }))
      .catch(() => {});
  }, [row?.Client]);

  async function handleGenerateMO() {
    setGeneratingMO(true);
    try {
      const { text } = await generateMarketOutlook();
      setMarketOutlook(text);
    } catch (e: unknown) {
      toast("error", `Market outlook failed: ${(e as Error).message}`);
    } finally {
      setGeneratingMO(false);
    }
  }

  async function handleGeneratePlan() {
    if (!row) return;
    setGeneratingPlan(true);
    try {
      const { text } = await generateClientPlan({
        client_name: row.Client,
        cluster: row.Cluster,
        recommended_product_type: row.Recommended_ProductType,
        confidence: row.Confidence,
        predicted_amount_sgd: row.Recommended_Amount_P50,
        avg_historical_amount: row.Avg_Historical_Amount,
        total_transactions: row.Total_Transactions,
        first_investment_date: row.First_Investment_Date,
        total_invested_sgd: row.Total_Invested_SGD,
        simple_language: !isTopBuyer(row.Top_10pct_Buyer),
      });
      setFuturePlan(text);
    } catch (e: unknown) {
      toast("error", `Plan generation failed: ${(e as Error).message}`);
    } finally {
      setGeneratingPlan(false);
    }
  }

  async function handleSendEmail() {
    if (!row?.Client_email) { toast("error", "No email on file for this client"); return; }
    setSendingEmail(true);
    try {
      await sendEmailReport(row.Client_email, includeMO ? marketOutlook || undefined : undefined, includePlan ? futurePlan || undefined : undefined);
      toast("success", "Email sent successfully");
    } catch (e: unknown) { toast("error", (e as Error).message); }
    finally { setSendingEmail(false); }
  }

  async function handleSendWA() {
    if (!row?.Client_phone_number) { toast("error", "No phone number on file"); return; }
    setSendingWA(true);
    try {
      await sendWhatsAppReport(String(row.Client_phone_number), includeMO ? marketOutlook || undefined : undefined, includePlan ? futurePlan || undefined : undefined);
      toast("success", "WhatsApp message sent");
    } catch (e: unknown) { toast("error", (e as Error).message); }
    finally { setSendingWA(false); }
  }

  if (!date) return null;

  return (
    <AnimatePresence>
      <motion.div className="drawer-overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
      <motion.div
        className="drawer"
        initial={{ x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{ type: "spring", stiffness: 320, damping: 32 }}
      >
        {/* Header */}
        <div className="drawer-header">
          <div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>{date}</div>
            {dayRecs.length > 0 && (
              <div className="nav-row">
                <button className="btn-icon" onClick={() => setIdx((i) => (i - 1 + dayRecs.length) % dayRecs.length)}>
                  <ChevronLeft size={16} />
                </button>
                <span className="nav-count">{idx + 1} / {dayRecs.length}</span>
                <button className="btn-icon" onClick={() => setIdx((i) => (i + 1) % dayRecs.length)}>
                  <ChevronRight size={16} />
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => setShowAll(true)} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                  <List size={13} /> Show all
                </button>
              </div>
            )}
          </div>
          <button className="btn-icon" onClick={onClose}>
            <X size={17} />
          </button>
        </div>

        <div className="drawer-body">
          {/* No data */}
          {dayRecs.length === 0 && dayReminders.length === 0 && (
            <div style={{ color: "var(--text-muted)", textAlign: "center", paddingTop: 40 }}>No records for this date.</div>
          )}

          {/* Client card */}
          {row && (
            <>
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 6 }}>{row.Client}</div>
                <span className="badge" style={{ background: clusterColor + "22", color: clusterColor, border: `1px solid ${clusterColor}55` }}>
                  {row.Cluster}
                </span>
              </div>

              {/* Info grid */}
              <div className="info-grid">
                <div className="info-item">
                  <div className="info-label">Recent Product</div>
                  <div className="info-value">{row.Current_ProductType || "—"}</div>
                </div>
                <div className="info-item">
                  <div className="info-label">Recent Date</div>
                  <div className="info-value">{row.Current_ProductType_Date || "—"}</div>
                </div>
                <div className="info-item">
                  <div className="info-label">Recommended</div>
                  <div className="info-value blue">{row.Recommended_ProductType || "—"}</div>
                </div>
                <div className="info-item">
                  <div className="info-label">Predicted Date</div>
                  <div className="info-value">{row.Predicted_Purchase_Date || row.EventDate || "—"}</div>
                </div>
                <div className="info-item">
                  <div className="info-label">P50 Amount</div>
                  <div className="info-value blue">{formatSGD(row.Recommended_Amount_P50)}</div>
                </div>
                <div className="info-item">
                  <div className="info-label">Range (P10–P90)</div>
                  <div className="info-value" style={{ fontSize: 12 }}>
                    {formatSGD(row.Recommended_Amount_P10)} – {formatSGD(row.Recommended_Amount_P90)}
                  </div>
                </div>
                <div className="info-item">
                  <div className="info-label">Confidence</div>
                  <div className="info-value green">{row.Confidence ?? "—"}</div>
                </div>
                <div className="info-item">
                  <div className="info-label">Top 10% Buyer</div>
                  <div className={`info-value ${isTopBuyer(row.Top_10pct_Buyer) ? "green" : "red"}`}>
                    {isTopBuyer(row.Top_10pct_Buyer) ? "Yes" : "No"}
                  </div>
                </div>
                <div className="info-item">
                  <div className="info-label">Total Transactions</div>
                  <div className="info-value">{row.Total_Transactions ?? "—"}</div>
                </div>
                <div className="info-item">
                  <div className="info-label">Total Invested</div>
                  <div className="info-value">{formatSGD(row.Total_Invested_SGD)}</div>
                </div>
              </div>

              {/* Live price */}
              {livePrice !== null && (
                <div className="info-item" style={{ marginBottom: 12 }}>
                  <div className="info-label" style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    <TrendingUp size={10} /> Live Price ({livePrice.product})
                  </div>
                  <div className="info-value blue">
                    {livePrice.price != null ? `$${livePrice.price.toLocaleString()}` : "—"}
                  </div>
                </div>
              )}

              <div className="divider" />

              {/* Market Outlook */}
              <div className="section-header">
                <span className="section-title" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <TrendingUp size={12} /> Market Outlook
                </span>
                <div className="flex gap-2">
                  {marketOutlook && !editingMO && (
                    <button className="btn-icon" style={{ width: 28, height: 28 }} onClick={() => { setEditMOText(marketOutlook); setEditingMO(true); }} title="Edit">
                      <Pencil size={13} />
                    </button>
                  )}
                  <button className="btn btn-ghost btn-sm" onClick={handleGenerateMO} disabled={generatingMO} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                    {generatingMO ? <><span className="spinner" /> Generating…</> : <><Sparkles size={13} /> Generate</>}
                  </button>
                </div>
              </div>
              {editingMO ? (
                <div>
                  <textarea className="textarea" value={editMOText} onChange={(e) => setEditMOText(e.target.value)} rows={6} />
                  <div className="flex gap-2 mt-2">
                    <button className="btn btn-primary btn-sm" onClick={() => { setMarketOutlook(editMOText); setEditingMO(false); }} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <Save size={13} /> Save
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => setEditingMO(false)} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <XIcon size={13} /> Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="ai-text-box" style={{ minHeight: 48 }}>
                  {marketOutlook || <span style={{ color: "var(--text-muted)", fontStyle: "italic" }}>Click &ldquo;Generate&rdquo; to create a personalized market outlook.</span>}
                </div>
              )}

              <div style={{ height: 14 }} />

              {/* Future Plan */}
              <div className="section-header">
                <span className="section-title" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <Bot size={12} /> Future Plan (AI Advisor)
                </span>
                <div className="flex gap-2">
                  {futurePlan && !editingPlan && (
                    <button className="btn-icon" style={{ width: 28, height: 28 }} onClick={() => { setEditPlanText(futurePlan); setEditingPlan(true); }} title="Edit">
                      <Pencil size={13} />
                    </button>
                  )}
                  <button className="btn btn-ghost btn-sm" onClick={handleGeneratePlan} disabled={generatingPlan} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                    {generatingPlan ? <><span className="spinner" /> Generating…</> : <><Sparkles size={13} /> Generate</>}
                  </button>
                </div>
              </div>
              {editingPlan ? (
                <div>
                  <textarea className="textarea" value={editPlanText} onChange={(e) => setEditPlanText(e.target.value)} rows={8} />
                  <div className="flex gap-2 mt-2">
                    <button className="btn btn-primary btn-sm" onClick={() => { setFuturePlan(editPlanText); setEditingPlan(false); }} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <Save size={13} /> Save
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => setEditingPlan(false)} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                      <XIcon size={13} /> Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="ai-text-box" style={{ minHeight: 48, whiteSpace: "pre-wrap" }}>
                  {futurePlan || <span style={{ color: "var(--text-muted)", fontStyle: "italic" }}>Click &ldquo;Generate&rdquo; to create a personalized plan for {row.Client}.</span>}
                </div>
              )}

              <div className="divider" />

              {/* Send section */}
              <div className="section-title" style={{ marginBottom: 10 }}>Send to Client</div>
              <div className="flex gap-3" style={{ marginBottom: 10, flexWrap: "wrap" }}>
                <label className="checkbox-row">
                  <input type="checkbox" checked={includeMO} onChange={(e) => setIncludeMO(e.target.checked)} />
                  Include Market Outlook
                </label>
                <label className="checkbox-row">
                  <input type="checkbox" checked={includePlan} onChange={(e) => setIncludePlan(e.target.checked)} />
                  Include Future Plan
                </label>
              </div>
              <div className="flex gap-2">
                <button className="btn btn-primary btn-sm" onClick={handleSendEmail} disabled={sendingEmail} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  {sendingEmail ? <><span className="spinner" /> Sending…</> : <><Mail size={13} /> Send Email</>}
                </button>
                <button className="btn btn-accent btn-sm" onClick={handleSendWA} disabled={sendingWA} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  {sendingWA ? <><span className="spinner" /> Sending…</> : <><MessageSquare size={13} /> WhatsApp</>}
                </button>
              </div>
            </>
          )}

          {/* Reminders */}
          {dayReminders.length > 0 && (
            <>
              <div className="divider" style={{ marginTop: 16 }} />
              <RemindersList
                date={date}
                reminders={dayReminders}
                allRecs={[]}
                writingProfile={writingProfile}
                onChanged={onRemindersChanged}
              />
            </>
          )}
        </div>

        {/* Show-all modal */}
        {showAll && (
          <div className="modal-overlay" onClick={() => setShowAll(false)}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <span className="font-semibold">All records for {date}</span>
                <button className="btn-icon" onClick={() => setShowAll(false)}><X size={16} /></button>
              </div>
              <div className="modal-body">
                <table className="data-table">
                  <thead>
                    <tr>
                      {["Client","Cluster","Recommended","P50 Amount","Confidence"].map((h) => (
                        <th key={h}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {dayRecs.map((r, i) => (
                      <tr key={i}>
                        <td>{r.Client}</td>
                        <td>{r.Cluster}</td>
                        <td>{r.Recommended_ProductType}</td>
                        <td>{formatSGD(r.Recommended_Amount_P50)}</td>
                        <td>{r.Confidence}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="modal-footer">
                <a
                  className="btn btn-primary btn-sm"
                  href={`data:text/csv;charset=utf-8,${encodeURIComponent(
                    [Object.keys(dayRecs[0] || {}).join(","), ...dayRecs.map((r) => Object.values(r).join(","))].join("\n")
                  )}`}
                  download={`calendar_${date}.csv`}
                  style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
                >
                  <Download size={13} /> Download CSV
                </a>
                <button className="btn btn-ghost btn-sm" onClick={() => setShowAll(false)} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                  <Check size={13} /> Close
                </button>
              </div>
            </div>
          </div>
        )}
      </motion.div>
    </AnimatePresence>
  );
}
