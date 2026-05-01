"use client";
import { useState, useEffect, useMemo, useCallback } from "react";
import dynamic from "next/dynamic";
import { BarChart2, CheckCircle, Layers, CalendarRange, Bell, Download } from "lucide-react";
import { Recommendation, Reminder, Filters, CalendarEvent, CLUSTER_COLORS } from "@/lib/types";
import { getRecommendations, getReminders, getProfile, retrainProfile } from "@/lib/api";
import Sidebar from "@/components/Sidebar";
import ClientDetailDrawer from "@/components/ClientDetailDrawer";
import AIAgentPanel from "@/components/AIAgentPanel";
import ToastContainer, { ToastItem, useToastRegister } from "@/components/Toast";
import { toast } from "@/components/Toast";

// FullCalendar must be client-side only
const CalendarView = dynamic(() => import("@/components/CalendarView"), { ssr: false });

function buildCalendarEvents(recs: Recommendation[], reminders: Reminder[], filters: Filters): CalendarEvent[] {
  const events: CalendarEvent[] = [];

  // Filter recs
  const filtered = recs.filter((r) => {
    if (!r.EventDate) return false;
    if (r.EventDate < filters.startDate || r.EventDate > filters.endDate) return false;
    if (filters.clusters.length && !filters.clusters.includes(r.Cluster || "")) return false;
    if (filters.clientSearch && r.Client !== filters.clientSearch.trim()) return false;
    return true;
  });

  // Group by date + cluster
  const grouped: Record<string, Recommendation[]> = {};
  for (const r of filtered) {
    const key = `${r.EventDate}__${r.Cluster}`;
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(r);
  }

  for (const key of Object.keys(grouped)) {
    const [d, cn] = key.split("__");
    const g = grouped[key].sort((a, b) => (b.Recommended_Amount_P50 || 0) - (a.Recommended_Amount_P50 || 0));
    const first = g[0].Client;
    const extra = g.length - 1;
    events.push({
      id: `day-${d}-${cn}`,
      title: extra > 0 ? `${first} +${extra}` : first,
      start: d,
      allDay: true,
      color: CLUSTER_COLORS[cn] || "#777",
      extendedProps: { date: d, cluster: cn },
    });
  }

  // Reminder events (red)
  const remFiltered = reminders.filter((r) => {
    if (!r.Date) return false;
    const d = r.Date.slice(0, 10);
    return d >= filters.startDate && d <= filters.endDate;
  });
  const remByDate: Record<string, number> = {};
  for (const r of remFiltered) {
    const d = r.Date!.slice(0, 10);
    remByDate[d] = (remByDate[d] || 0) + 1;
  }
  for (const [d, count] of Object.entries(remByDate)) {
    events.push({
      id: `rem-${d}`,
      title: count === 1 ? "Reminder" : `Reminder +${count - 1}`,
      start: d,
      allDay: true,
      color: "#ef4444",
      extendedProps: { date: d, kind: "reminder" },
    });
  }

  return events;
}

export default function HomePage() {
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [writingProfile, setWritingProfile] = useState("");
  const [loading, setLoading] = useState(true);
  const [retraining, setRetraining] = useState(false);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  // Default date range: today ± 1 year
  const today = new Date();
  const defaultStart = new Date(today); defaultStart.setFullYear(today.getFullYear() - 1);
  const defaultEnd = new Date(today); defaultEnd.setFullYear(today.getFullYear() + 1);

  const [filters, setFilters] = useState<Filters>({
    startDate: defaultStart.toISOString().slice(0, 10),
    endDate: defaultEnd.toISOString().slice(0, 10),
    clusters: [],
    clientSearch: "",
  });

  useToastRegister(setToasts);

  const fetchData = useCallback(async () => {
    try {
      const [r, rem, prof] = await Promise.all([getRecommendations(), getReminders(), getProfile()]);
      setRecs(r);
      setReminders(rem);
      setWritingProfile(prof.text);
      // default clusters to all
      setFilters((f) => ({
        ...f,
        clusters: f.clusters.length === 0
          ? [...new Set(r.map((x) => x.Cluster).filter(Boolean))] as string[]
          : f.clusters,
      }));
    } catch (e: unknown) {
      toast("error", `Failed to load data: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const allClusters = useMemo(() => [...new Set(recs.map((r) => r.Cluster).filter(Boolean))] as string[], [recs]);

  const events = useMemo(() => buildCalendarEvents(recs, reminders, filters), [recs, reminders, filters]);

  const filteredRecs = useMemo(() => {
    return recs.filter((r) => {
      if (!r.EventDate) return false;
      if (r.EventDate < filters.startDate || r.EventDate > filters.endDate) return false;
      if (filters.clusters.length && !filters.clusters.includes(r.Cluster || "")) return false;
      if (filters.clientSearch && r.Client !== filters.clientSearch.trim()) return false;
      return true;
    });
  }, [recs, filters]);

  // Day data for selected date
  const dayRecs = useMemo(() => {
    if (!selectedDate) return [];
    return recs.filter((r) => r.EventDate?.slice(0, 10) === selectedDate);
  }, [recs, selectedDate]);

  const dayReminders = useMemo(() => {
    if (!selectedDate) return [];
    return reminders.filter((r) => r.Date?.slice(0, 10) === selectedDate);
  }, [reminders, selectedDate]);

  // Focus date for client search
  const focusDate = useMemo(() => {
    if (!filters.clientSearch) return undefined;
    const match = recs.find((r) => r.Client === filters.clientSearch.trim() && r.EventDate);
    return match?.EventDate?.slice(0, 10);
  }, [filters.clientSearch, recs]);

  async function handleRetrainProfile() {
    setRetraining(true);
    try {
      const edited = reminders
        .filter((r) => r.Edited === "1")
        .sort((a, b) => ((b["Date of edit"] || "") > (a["Date of edit"] || "") ? 1 : -1))
        .slice(0, 20)
        .map((r) => ({ subject: r.Subject || "", content: r.Content || "" }));
      if (!edited.length) { toast("info", "No edited reminders to train from"); return; }
      const { changed } = await retrainProfile(edited);
      if (changed) {
        const prof = await getProfile();
        setWritingProfile(prof.text);
        toast("success", "Writing profile retrained!");
      } else {
        toast("info", "No significant changes generated");
      }
    } catch (e: unknown) { toast("error", (e as Error).message); }
    finally { setRetraining(false); }
  }

  // Status bar info
  const minDate = filteredRecs.reduce((m, r) => (!m || r.EventDate! < m ? r.EventDate! : m), "");
  const maxDate = filteredRecs.reduce((m, r) => (!m || r.EventDate! > m ? r.EventDate! : m), "");

  return (
    <div className="app-layout">
      <Sidebar
        filters={filters}
        onFiltersChange={setFilters}
        allClusters={allClusters}
        rowCount={recs.length}
        writingProfile={writingProfile}
        onRetrainProfile={handleRetrainProfile}
        retraining={retraining}
      />

      <div className="main-content">
        {/* Header */}
        <header className="app-header">
          <div className="finpulse-title">FinPulse</div>
          <div className="status-bar">
            <span className="status-chip"><BarChart2 size={11} style={{display:"inline",verticalAlign:"middle",marginRight:4}}/>{recs.length} rows loaded</span>
            <span className="status-chip"><CheckCircle size={11} style={{display:"inline",verticalAlign:"middle",marginRight:4}}/>{recs.filter((r) => r.EventDate).length} with dates</span>
            <span className="status-chip"><Layers size={11} style={{display:"inline",verticalAlign:"middle",marginRight:4}}/>{allClusters.length} clusters</span>
            {minDate && <span className="status-chip"><CalendarRange size={11} style={{display:"inline",verticalAlign:"middle",marginRight:4}}/>{minDate} &rarr; {maxDate}</span>}
            <span className="status-chip"><Bell size={11} style={{display:"inline",verticalAlign:"middle",marginRight:4}}/>{reminders.length} reminders</span>
          </div>
        </header>

        {/* Calendar area */}
        <div className="calendar-area">
          {loading ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 400, gap: 12, color: "var(--text-muted)" }}>
              <span className="spinner" style={{ width: 24, height: 24, borderWidth: 3 }} />
              Loading FinPulse data…
            </div>
          ) : (
            <>
              <AIAgentPanel onConfirmed={fetchData} />
              <CalendarView
                events={events}
                onDateClick={setSelectedDate}
                onEventClick={setSelectedDate}
                initialDate={focusDate}
              />
            </>
          )}
        </div>

        {/* Bottom filtered table */}
        {!loading && (
          <div className="bottom-table-section">
            <table className="data-table">
              <thead>
                <tr>
                  {["Client","Cluster","Recommended","P50 Amount","Confidence","Event Date"].map((h) => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredRecs
                  .sort((a, b) => {
                    if (!a.EventDate) return 1;
                    if (!b.EventDate) return -1;
                    return a.EventDate > b.EventDate ? 1 : -1;
                  })
                  .slice(0, 200)
                  .map((r, i) => (
                    <tr key={i} onClick={() => setSelectedDate(r.EventDate?.slice(0,10) || null)} style={{ cursor: "pointer" }}>
                      <td>{r.Client}</td>
                      <td>
                        <span className="badge" style={{ background: (CLUSTER_COLORS[r.Cluster||""]||"#777") + "22", color: CLUSTER_COLORS[r.Cluster||""]||"#777", fontSize: 10 }}>
                          {r.Cluster}
                        </span>
                      </td>
                      <td>{r.Recommended_ProductType}</td>
                      <td>{r.Recommended_Amount_P50 != null ? `$${r.Recommended_Amount_P50.toLocaleString()}` : "—"}</td>
                      <td>{r.Confidence}</td>
                      <td>{r.EventDate}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
            {filteredRecs.length > 0 && (
              <div style={{ padding: "8px 12px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{filteredRecs.length} rows (showing up to 200)</span>
                <a
                  className="btn btn-ghost btn-sm"
                  href={`data:text/csv;charset=utf-8,${encodeURIComponent(
                    [Object.keys(filteredRecs[0] || {}).join(","), ...filteredRecs.map((r) => Object.values(r).map((v) => (v == null ? "" : String(v))).join(","))].join("\n")
                  )}`}
                  download="filtered_recommendations.csv"
                  style={{display:"inline-flex",alignItems:"center",gap:6}}
                >
                  <Download size={13}/> Download CSV
                </a>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Detail Drawer */}
      {selectedDate && (
        <ClientDetailDrawer
          date={selectedDate}
          dayRecs={dayRecs}
          dayReminders={dayReminders}
          onClose={() => setSelectedDate(null)}
          onRemindersChanged={fetchData}
          writingProfile={writingProfile}
        />
      )}

      <ToastContainer toasts={toasts} onRemove={(id) => setToasts((t) => t.filter((x) => x.id !== id))} />
    </div>
  );
}
