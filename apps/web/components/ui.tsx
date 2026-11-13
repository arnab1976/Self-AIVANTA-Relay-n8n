'use client';

import { useEffect, useState } from 'react';
import { STATUS_TONE } from '@/lib/format';

export function Pill({ children, tone }: { children: React.ReactNode; tone?: string }) {
  const t = tone ?? STATUS_TONE[String(children)] ?? 'plain';
  return <span className={`pill ${t}`}>{children}</span>;
}

export function Card({ title, actions, children, className = '' }: { title?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          <h3>{title}</h3>
          {actions && <div className="row">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, sub, actions }: { title: string; sub?: string; actions?: React.ReactNode }) {
  return (
    <div className="ph">
      <div>
        <h1>{title}</h1>
        {sub && <p className="sub">{sub}</p>}
      </div>
      {actions && <div className="row ph-actions">{actions}</div>}
    </div>
  );
}

export function Kpi({ label, value, note }: { label: string; value: React.ReactNode; note?: React.ReactNode }) {
  return (
    <div className="card kpi">
      <small>{label}</small>
      <b>{value}</b>
      {note && <span className="muted">{note}</span>}
    </div>
  );
}

let pushToast: ((m: string, err?: boolean) => void) | null = null;
export function toast(message: string, error = false) {
  pushToast?.(message, error);
}

export function Toaster() {
  const [items, setItems] = useState<{ id: number; m: string; err: boolean }[]>([]);
  useEffect(() => {
    pushToast = (m, err = false) => {
      const id = Date.now() + Math.random();
      setItems((x) => [...x, { id, m, err }]);
      setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 4200);
    };
    return () => {
      pushToast = null;
    };
  }, []);
  return (
    <div className="toasts" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast ${t.err ? 'err' : ''}`}>{t.m}</div>
      ))}
    </div>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <header className="card-head">
          <h3>{title}</h3>
          <button className="btn ghost" onClick={onClose} aria-label="Close">✕</button>
        </header>
        {children}
      </div>
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="muted empty">{children}</p>;
}
