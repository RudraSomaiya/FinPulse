"use client";
import { useEffect, useRef } from "react";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin from "@fullcalendar/interaction";
import { CalendarEvent } from "@/lib/types";

interface CalendarViewProps {
  events: CalendarEvent[];
  onDateClick: (date: string) => void;
  onEventClick: (date: string) => void;
  initialDate?: string;
}

export default function CalendarView({ events, onDateClick, onEventClick, initialDate }: CalendarViewProps) {
  const calRef = useRef<FullCalendar>(null);

  // If initialDate changes (client search), navigate calendar to that date
  useEffect(() => {
    if (initialDate && calRef.current) {
      calRef.current.getApi().gotoDate(initialDate);
    }
  }, [initialDate]);

  return (
    <div style={{ background: "rgba(255,255,255,0.02)", borderRadius: "var(--radius)", border: "1px solid var(--border)", padding: "16px 12px" }}>
      <FullCalendar
        ref={calRef}
        plugins={[dayGridPlugin, interactionPlugin]}
        initialView="dayGridMonth"
        height={680}
        headerToolbar={{
          left: "prev,next today",
          center: "title",
          right: "dayGridMonth,dayGridWeek,dayGridDay",
        }}
        events={events}
        dateClick={(info) => onDateClick(info.dateStr)}
        eventClick={(info) => {
          const d =
            info.event.extendedProps?.date ||
            (info.event.start ? info.event.start.toISOString().slice(0, 10) : "");
          if (d) onEventClick(d);
        }}
        eventDisplay="block"
        dayMaxEvents={3}
      />
    </div>
  );
}
