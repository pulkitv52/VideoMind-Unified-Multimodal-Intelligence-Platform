import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
export type EvidenceMode = "dialog" | "panel";
export function EvidenceFrame({ mode = "dialog", title, subtitle, onClose, children }: { mode?: EvidenceMode; title: string; subtitle: string; onClose: () => void; children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (mode === "dialog") {
      const element = dialog.current;
      const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      element?.showModal();
      return () => { element?.close(); if (previous?.isConnected) previous.focus(); };
    }
    heading.current?.focus({ preventScroll: true });
  }, [mode]);
  const contents = <><div className="document-toolbar"><div><h2 id="evidence-title" ref={heading} tabIndex={-1}>{title}</h2><p className="muted">{subtitle}</p></div><button className="secondary evidence-close" onClick={onClose}>{mode === "panel" ? "Back to results" : "Close evidence"}</button></div>{children}</>;
  return mode === "panel" ? <section className="evidence-content" aria-labelledby="evidence-title">{contents}</section> : <dialog ref={dialog} className="document-dialog" onCancel={onClose} aria-labelledby="evidence-title">{contents}</dialog>;
}
