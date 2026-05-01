// Shared TypeScript types for FinPulse

export interface Recommendation {
  Client: string;
  Cluster: string;
  EventDate: string | null;
  Recommended_ProductType: string | null;
  Predicted_Purchase_Date: string | null;
  Recommended_Amount_P10: number | null;
  Recommended_Amount_P50: number | null;
  Recommended_Amount_P90: number | null;
  Current_ProductType: string | null;
  Current_ProductType_Date: string | null;
  Confidence: string | null;
  Top_10pct_Buyer: string | boolean | null;
  Client_email: string | null;
  Client_phone_number: string | null;
  Client_Birthdate: string | null;
  Avg_Historical_Amount: number | null;
  Total_Transactions: number | null;
  First_Investment_Date: string | null;
  Total_Invested_SGD: number | null;
  Recent_Product: string | null;
  Recent_Date: string | null;
  [key: string]: unknown;
}

export interface Reminder {
  ReminderId: string;
  Client: string | null;
  Date: string | null;
  Subject: string | null;
  Content: string | null;
  Edited: string | null;
  "Date of edit": string | null;
}

export interface CalendarEvent {
  id: string;
  title: string;
  start: string;
  allDay: boolean;
  color: string;
  extendedProps: {
    date: string;
    cluster?: string;
    kind?: string;
  };
}

export interface AgentPlanItem {
  client?: string;
  date?: string;
  title?: string;
  amount?: number | null;
  use_client_birthdate?: boolean;
  content?: string | null;
  id?: string;
  fields?: Record<string, string | null>;
  field?: string;
  value?: number | string;
}

export interface AgentPlan {
  reasoning: string;
  events_to_create: AgentPlanItem[];
  events_to_modify: AgentPlanItem[];
  events_to_delete: string[];
  recommendation_changes: AgentPlanItem[];
}

export interface Filters {
  startDate: string;
  endDate: string;
  clusters: string[];
  clientSearch: string;
}

export const CLUSTER_COLORS: Record<string, string> = {
  "Passive Long-Term Investor": "#3b82f6",
  "Regular Retail Investor": "#f97316",
  "Ultra High-Net-Worth": "#10b981",
  "New/Single-Transaction": "#8b5cf6",
};
