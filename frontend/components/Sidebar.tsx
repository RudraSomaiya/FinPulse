"use client";
import { Filters, CLUSTER_COLORS } from "@/lib/types";
import { useState } from "react";
import { ChevronDown, ChevronUp, Eye, EyeOff, RefreshCw } from "lucide-react";

interface SidebarProps {
  filters: Filters;
  onFiltersChange: (f: Filters) => void;
  allClusters: string[];
  rowCount: number;
  writingProfile: string;
  onRetrainProfile: () => void;
  retraining: boolean;
}

export default function Sidebar({
  filters,
  onFiltersChange,
  allClusters,
  rowCount,
  writingProfile,
  onRetrainProfile,
  retraining,
}: SidebarProps) {
  const [profileOpen, setProfileOpen] = useState(false);
  const [showProfileText, setShowProfileText] = useState(false);

  function toggleCluster(c: string) {
    const next = filters.clusters.includes(c)
      ? filters.clusters.filter((x) => x !== c)
      : [...filters.clusters, c];
    onFiltersChange({ ...filters, clusters: next });
  }

  function toggleAllClusters() {
    const all = allClusters.length === filters.clusters.length;
    onFiltersChange({ ...filters, clusters: all ? [] : [...allClusters] });
  }

  return (
    <aside className="sidebar">
      {/* Logo */}
      <div className="sidebar-logo">
        <img src="/logo.webp" alt="AiGENThix" onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
        <div style={{ marginTop: 8, fontFamily: "'Outfit',sans-serif", fontWeight: 800, fontSize: "1.3rem", background: "linear-gradient(135deg,#3b82f6,#10b981)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
          FinPulse
        </div>
      </div>

      {/* Writing Profile */}
      <div className="sidebar-section">
        <p className="sidebar-section-title">Writing Profile</p>
        <button className="expander-trigger" onClick={() => setProfileOpen((o) => !o)} style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span>Manage Profile</span>
          {profileOpen ? <ChevronUp size={13} style={{ opacity: 0.6 }} /> : <ChevronDown size={13} style={{ opacity: 0.6 }} />}
        </button>
        {profileOpen && (
          <div className="expander-body">
            <button className="btn btn-ghost btn-sm w-full" style={{ marginBottom: 6, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6 }} onClick={() => setShowProfileText((v) => !v)}>
              {showProfileText ? <><EyeOff size={13} /> Hide Profile</> : <><Eye size={13} /> Show Profile</>}
            </button>
            {showProfileText && writingProfile && (
              <div className="ai-text-box" style={{ maxHeight: 180, overflowY: "auto", fontSize: 11, marginBottom: 8 }}>
                {writingProfile}
              </div>
            )}
            <button className="btn btn-primary btn-sm w-full" onClick={onRetrainProfile} disabled={retraining} style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
              {retraining ? <><span className="spinner" /> Retraining…</> : <><RefreshCw size={13} /> Retrain Writing Style</>}
            </button>
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="sidebar-section">
        <p className="sidebar-section-title">Date Range</p>
        <div className="flex-col gap-2">
          <div className="date-row">
            <label>From</label>
            <input
              type="date"
              className="input"
              value={filters.startDate}
              onChange={(e) => onFiltersChange({ ...filters, startDate: e.target.value })}
            />
          </div>
          <div className="date-row">
            <label>To</label>
            <input
              type="date"
              className="input"
              value={filters.endDate}
              onChange={(e) => onFiltersChange({ ...filters, endDate: e.target.value })}
            />
          </div>
        </div>
      </div>

      <div className="sidebar-section">
        <div className="flex items-center justify-between" style={{ marginBottom: 8 }}>
          <p className="sidebar-section-title" style={{ margin: 0 }}>Clusters</p>
          <button className="btn btn-ghost btn-sm" onClick={toggleAllClusters}>
            {filters.clusters.length === allClusters.length ? "None" : "All"}
          </button>
        </div>
        <div className="cluster-chips">
          {allClusters.map((c) => (
            <div key={c} className={`cluster-chip ${filters.clusters.includes(c) ? "selected" : ""}`} onClick={() => toggleCluster(c)}>
              <span className="cluster-dot" style={{ background: CLUSTER_COLORS[c] || "#777" }} />
              <span style={{ flex: 1, fontSize: 11 }}>{c}</span>
              {filters.clusters.includes(c) && <span style={{ fontSize: 10, color: "var(--primary)" }}>✓</span>}
            </div>
          ))}
        </div>
      </div>

      <div className="sidebar-section">
        <p className="sidebar-section-title">Client Search</p>
        <input
          type="text"
          className="input"
          placeholder="Search by client ID…"
          value={filters.clientSearch}
          onChange={(e) => onFiltersChange({ ...filters, clientSearch: e.target.value })}
        />
      </div>

      {/* Legend */}
      <div className="sidebar-section">
        <p className="sidebar-section-title">Legend</p>
        <div className="flex-col gap-2">
          {Object.entries(CLUSTER_COLORS).map(([name, color]) => (
            <div key={name} className="flex items-center gap-2" style={{ fontSize: 11, color: "var(--text-secondary)" }}>
              <span style={{ width: 10, height: 10, borderRadius: "50%", background: color, flexShrink: 0, display: "inline-block" }} />
              {name}
            </div>
          ))}
          <div className="flex items-center gap-2" style={{ fontSize: 11, color: "var(--text-secondary)" }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", background: "#ef4444", flexShrink: 0, display: "inline-block" }} />
            Reminders
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="sidebar-section" style={{ marginTop: "auto" }}>
        <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.8 }}>
          <div>{rowCount} recommendations loaded</div>
        </div>
      </div>
    </aside>
  );
}
