"use client";
import { useEffect } from "react";
import { CheckCircle, XCircle, Info, X } from "lucide-react";

interface ToastItem {
  id: string;
  type: "success" | "error" | "info";
  message: string;
}

interface ToastContainerProps {
  toasts: ToastItem[];
  onRemove: (id: string) => void;
}

const ICONS = {
  success: <CheckCircle size={15} />,
  error: <XCircle size={15} />,
  info: <Info size={15} />,
};

export default function ToastContainer({ toasts, onRemove }: ToastContainerProps) {
  return (
    <div className="toast-container">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.type}`}>
          {ICONS[t.type]}
          <span style={{ flex: 1 }}>{t.message}</span>
          <button
            onClick={() => onRemove(t.id)}
            style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", display: "flex", alignItems: "center" }}
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}

let _setToasts: React.Dispatch<React.SetStateAction<ToastItem[]>> | null = null;

export function toast(type: ToastItem["type"], message: string) {
  if (!_setToasts) return;
  const id = Math.random().toString(36).slice(2);
  _setToasts((prev) => [...prev, { id, type, message }]);
  setTimeout(() => {
    _setToasts?.((prev) => prev.filter((t) => t.id !== id));
  }, 4000);
}

export function useToastRegister(setToasts: React.Dispatch<React.SetStateAction<ToastItem[]>>) {
  useEffect(() => {
    _setToasts = setToasts;
    return () => { _setToasts = null; };
  }, [setToasts]);
}

export type { ToastItem };
