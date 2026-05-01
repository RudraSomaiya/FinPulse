"use client";
import { useState } from "react";
import { Pencil, Save, X, Sparkles, Mail, MessageSquare, Trash2 } from "lucide-react";
import { Reminder, Recommendation } from "@/lib/types";
import { updateReminder, deleteReminders, sendEmailReminder, sendWhatsAppReminder, generateReminderContent } from "@/lib/api";
import { toast } from "./Toast";

interface RemindersListProps {
  date: string;
  reminders: Reminder[];
  allRecs: Recommendation[];
  writingProfile: string;
  onChanged: () => void;
}

export default function RemindersList({ date, reminders, allRecs, onChanged }: RemindersListProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editSubject, setEditSubject] = useState("");
  const [editContent, setEditContent] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [generatingId, setGeneratingId] = useState<string | null>(null);
  const [genPromptId, setGenPromptId] = useState<string | null>(null);
  const [genPrompt, setGenPrompt] = useState("");
  const [bulkSendingEmail, setBulkSendingEmail] = useState(false);
  const [bulkSendingWA, setBulkSendingWA] = useState(false);
  const [deleting, setDeleting] = useState(false);

  function toggleSelect(id: string) {
    setSelected((s) => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  }

  function toggleAll() {
    setSelected(selected.size === reminders.length ? new Set() : new Set(reminders.map((r) => r.ReminderId)));
  }

  function getClientEmail(clientName: string | null) {
    if (!clientName) return null;
    const rec = allRecs.find((r) => r.Client === clientName);
    return rec?.Client_email || null;
  }

  function getClientPhone(clientName: string | null) {
    if (!clientName) return null;
    const rec = allRecs.find((r) => r.Client === clientName);
    return rec?.Client_phone_number ? String(rec.Client_phone_number) : null;
  }

  async function startEdit(r: Reminder) {
    setEditingId(r.ReminderId);
    setEditSubject(r.Subject || "");
    setEditContent(r.Content || "");
  }

  async function saveEdit(r: Reminder) {
    setSavingId(r.ReminderId);
    try {
      await updateReminder(r.ReminderId, { subject: editSubject, content: editContent });
      onChanged();
      setEditingId(null);
      toast("success", "Reminder updated");
    } catch (e: unknown) { toast("error", (e as Error).message); }
    finally { setSavingId(null); }
  }

  async function handleBulkDelete() {
    const ids = [...selected];
    if (!ids.length) { toast("info", "No reminders selected"); return; }
    setDeleting(true);
    try {
      await deleteReminders(ids);
      onChanged();
      setSelected(new Set());
      toast("success", `Deleted ${ids.length} reminder(s)`);
    } catch (e: unknown) { toast("error", (e as Error).message); }
    finally { setDeleting(false); }
  }

  async function handleBulkEmail() {
    const ids = [...selected];
    if (!ids.length) { toast("info", "No reminders selected"); return; }
    setBulkSendingEmail(true);
    let ok = 0;
    for (const id of ids) {
      const r = reminders.find((x) => x.ReminderId === id);
      if (!r) continue;
      const email = getClientEmail(r.Client);
      if (!email) { toast("error", `No email for ${r.Client}`); continue; }
      try { await sendEmailReminder(email, r.Subject || "", r.Content || ""); ok++; }
      catch (e: unknown) { toast("error", (e as Error).message); }
    }
    if (ok) toast("success", `Sent ${ok} email(s)`);
    setBulkSendingEmail(false);
  }

  async function handleBulkWA() {
    const ids = [...selected];
    if (!ids.length) { toast("info", "No reminders selected"); return; }
    setBulkSendingWA(true);
    let ok = 0;
    for (const id of ids) {
      const r = reminders.find((x) => x.ReminderId === id);
      if (!r) continue;
      const phone = getClientPhone(r.Client);
      if (!phone) { toast("error", `No phone for ${r.Client}`); continue; }
      try { await sendWhatsAppReminder(phone, r.Subject || "", r.Content || ""); ok++; }
      catch (e: unknown) { toast("error", (e as Error).message); }
    }
    if (ok) toast("success", `Sent ${ok} WhatsApp message(s)`);
    setBulkSendingWA(false);
  }

  async function handleGenerateContent(r: Reminder) {
    if (!genPrompt.trim()) { toast("info", "Enter a prompt first"); return; }
    setGeneratingId(r.ReminderId);
    try {
      const { text } = await generateReminderContent(r.Subject || "", genPrompt);
      await updateReminder(r.ReminderId, { content: text });
      onChanged();
      setGenPromptId(null);
      setGenPrompt("");
      toast("success", "Content generated and saved");
    } catch (e: unknown) { toast("error", (e as Error).message); }
    finally { setGeneratingId(null); }
  }

  return (
    <div>
      <div className="flex items-center justify-between" style={{ marginBottom: 10 }}>
        <span className="section-title">Reminders ({reminders.length})</span>
        <label className="checkbox-row" style={{ fontSize: 11 }}>
          <input type="checkbox" checked={selected.size === reminders.length && reminders.length > 0} onChange={toggleAll} />
          Select all
        </label>
      </div>

      {/* Bulk actions */}
      <div className="flex gap-2" style={{ marginBottom: 12, flexWrap: "wrap" }}>
        <button className="btn btn-primary btn-sm" onClick={handleBulkEmail} disabled={bulkSendingEmail} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          {bulkSendingEmail ? <><span className="spinner" /> Sending…</> : <><Mail size={13} /> Email</>}
        </button>
        <button className="btn btn-accent btn-sm" onClick={handleBulkWA} disabled={bulkSendingWA} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          {bulkSendingWA ? <><span className="spinner" /> Sending…</> : <><MessageSquare size={13} /> WhatsApp</>}
        </button>
        <button className="btn btn-danger btn-sm" onClick={handleBulkDelete} disabled={deleting} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          {deleting ? <><span className="spinner" /> Deleting…</> : <><Trash2 size={13} /> Delete</>}
        </button>
      </div>

      {reminders.map((r) => {
        const isEditing = editingId === r.ReminderId;
        const isGenOpen = genPromptId === r.ReminderId;
        return (
          <div key={r.ReminderId} className="reminder-card">
            <div className="reminder-card-header">
              <input type="checkbox" checked={selected.has(r.ReminderId)} onChange={() => toggleSelect(r.ReminderId)} style={{ accentColor: "var(--danger)" }} />
              {isEditing ? (
                <input className="input" value={editSubject} onChange={(e) => setEditSubject(e.target.value)} style={{ flex: 1 }} />
              ) : (
                <span className="reminder-subject">{r.Subject || "(No subject)"}</span>
              )}
              {r.Client && <span className="badge badge-red" style={{ fontSize: 10 }}>{r.Client}</span>}
            </div>

            {isEditing ? (
              <>
                <textarea className="textarea" style={{ marginTop: 8 }} value={editContent} onChange={(e) => setEditContent(e.target.value)} rows={4} />
                <div className="flex gap-2 mt-2">
                  <button className="btn btn-primary btn-sm" onClick={() => saveEdit(r)} disabled={savingId === r.ReminderId} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                    {savingId === r.ReminderId ? <><span className="spinner" /> Saving…</> : <><Save size={13} /> Save</>}
                  </button>
                  <button className="btn btn-ghost btn-sm" onClick={() => setEditingId(null)} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                    <X size={13} /> Cancel
                  </button>
                </div>
              </>
            ) : (
              <div className="reminder-content">{r.Content || "(No content)"}</div>
            )}

            {isGenOpen && (
              <div className="flex gap-2 mt-2 items-center">
                <input className="input" placeholder="Describe what to generate…" value={genPrompt} onChange={(e) => setGenPrompt(e.target.value)} style={{ flex: 1 }} />
                <button className="btn btn-primary btn-sm" onClick={() => handleGenerateContent(r)} disabled={generatingId === r.ReminderId} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                  {generatingId === r.ReminderId ? <span className="spinner" /> : <><Sparkles size={12} /> Send</>}
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => { setGenPromptId(null); setGenPrompt(""); }}>
                  <X size={13} />
                </button>
              </div>
            )}

            <div className="reminder-actions">
              {!isEditing && (
                <button className="btn btn-ghost btn-sm" onClick={() => startEdit(r)} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                  <Pencil size={12} /> Edit
                </button>
              )}
              {!isGenOpen && !isEditing && (
                <button className="btn btn-ghost btn-sm" onClick={() => { setGenPromptId(r.ReminderId); setGenPrompt(""); }} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                  <Sparkles size={12} /> Generate
                </button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
