// API client for FinPulse backend
import { AgentPlan, Recommendation, Reminder } from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// Recommendations
export const getRecommendations = (): Promise<Recommendation[]> =>
  request("/api/recommendations");

// Reminders
export const getReminders = (): Promise<Reminder[]> =>
  request("/api/reminders");

export const createReminder = (body: {
  client: string;
  date: string;
  title: string;
  content?: string;
  amount?: number;
}) => request("/api/reminders", { method: "POST", body: JSON.stringify(body) });

export const updateReminder = (
  id: string,
  body: { subject?: string; content?: string }
) =>
  request(`/api/reminders/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteReminders = (ids: string[]) =>
  request("/api/reminders", {
    method: "DELETE",
    body: JSON.stringify({ ids }),
  });

// Agent
export const generateAgentPlan = (
  query: string,
  profileText?: string
): Promise<AgentPlan> =>
  request("/api/agent/plan", {
    method: "POST",
    body: JSON.stringify({ query, profile_text: profileText }),
  });

export const confirmAgentPlan = (plan: AgentPlan) =>
  request("/api/agent/confirm", {
    method: "POST",
    body: JSON.stringify({ plan }),
  });

// LLM
export const getProfile = (): Promise<{ text: string }> =>
  request("/api/llm/profile");

export const generateMarketOutlook = (): Promise<{ text: string }> =>
  request("/api/llm/market-outlook", { method: "POST", body: JSON.stringify({}) });

export const generateClientPlan = (
  context: Record<string, unknown>
): Promise<{ text: string }> =>
  request("/api/llm/client-plan", {
    method: "POST",
    body: JSON.stringify({ context }),
  });

export const generateReminderContent = (
  title: string,
  prompt: string
): Promise<{ text: string }> =>
  request("/api/llm/reminder-content", {
    method: "POST",
    body: JSON.stringify({ title, prompt }),
  });

export const retrainProfile = (
  editedReminders: Array<{ subject: string; content: string }>
): Promise<{ text: string; changed: boolean }> =>
  request("/api/llm/retrain-profile", {
    method: "POST",
    body: JSON.stringify({ edited_reminders: editedReminders }),
  });

// Comms
export const sendEmailReport = (
  recipient: string,
  marketOutlook?: string,
  futurePlan?: string
) =>
  request("/api/comms/email/report", {
    method: "POST",
    body: JSON.stringify({
      recipient,
      market_outlook: marketOutlook,
      future_plan: futurePlan,
    }),
  });

export const sendEmailReminder = (
  recipient: string,
  subject: string,
  content: string
) =>
  request("/api/comms/email/reminder", {
    method: "POST",
    body: JSON.stringify({ recipient, subject, content }),
  });

export const sendWhatsAppReport = (
  recipient: string,
  marketOutlook?: string,
  futurePlan?: string
) =>
  request("/api/comms/whatsapp/report", {
    method: "POST",
    body: JSON.stringify({
      recipient,
      market_outlook: marketOutlook,
      future_plan: futurePlan,
    }),
  });

export const sendWhatsAppReminder = (
  recipient: string,
  subject: string,
  content: string
) =>
  request("/api/comms/whatsapp/reminder", {
    method: "POST",
    body: JSON.stringify({ recipient, subject, content }),
  });

// Market
export const getLivePrice = (
  ticker: string
): Promise<{ ticker: string; price: number | null }> =>
  request(`/api/market/price?ticker=${encodeURIComponent(ticker)}`);
