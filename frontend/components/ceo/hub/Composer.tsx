"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { Spinner } from "@/components/ui/LoadingState";

const ACCEPT = ".png,.jpg,.jpeg,.webp,.pdf,.csv,.xlsx";

/** The chat bar: always at the bottom. Whatever the CEO or an agent asks, the answer is typed here (the backend parses it against the one question that
 * was asked). Enter sends, Shift+Enter adds a line. Files are attached with the + button; their type is decided by the backend from the content. */
export type FileStatus = "uploading" | "uploaded" | "failed";
const STATUS_WORDS: Record<FileStatus, string> = { uploading: "Uploading…", uploaded: "Attached", failed: "Not attached" };
const sizeOf = (n: number) => (n < 1024 ? `${n} B` : n < 1048576 ? `${n >> 10} KB` : `${n >> 20} MB`); // a file size, not money: whole units by bit shift (the hub does no number formatting)

export function Composer({
  disabled, placeholder, onSend, error, fileStatus, fileInfo, initialText,
}: {
  /** A draft to start with (from a link in another page). The seller reads it, can edit it, and sends it: nothing is sent by arriving here. */
  initialText?: string;
  disabled: boolean; placeholder: string; error?: string | null; fileStatus?: (f: File) => FileStatus | undefined;
  /** What the backend reported about a file once it was uploaded (for a spreadsheet: its sheets and size, or why it could not be read as a table). */
  fileInfo?: (f: File) => string | undefined;
  /** May return a promise; resolving to `false` means the message was NOT sent (an upload failed): the text and the files are kept so the seller can retry. */
  onSend: (text: string, files: File[]) => void | boolean | Promise<void | boolean>;
}) {
  const [text, setText] = useState(initialText ?? "");
  const [files, setFiles] = useState<File[]>([]);
  const [sending, setSending] = useState(false);
  const [dragging, setDragging] = useState(false);
  // the same file picked twice is one file (name, size and modified time are the identity the browser gives us)
  const addFiles = (incoming: File[]) => setFiles((fs) => [...fs, ...incoming.filter((f) => !fs.some((g) => g.name === f.name && g.size === f.size && g.lastModified === f.lastModified))]);
  const picker = useRef<HTMLInputElement | null>(null);
  const box = useRef<HTMLTextAreaElement | null>(null);
  const canSend = !disabled && !sending && (text.trim().length > 0 || files.length > 0);
  const submit = async () => {
    if (!canSend) return;
    setSending(true);
    let ok: void | boolean = true;
    try {
      ok = await onSend(text.trim(), files);
    } finally {
      setSending(false);
    }
    if (ok === false) return; // nothing was sent: keep what the seller typed and attached so a retry is one click
    setText("");
    setFiles([]);
    if (box.current) box.current.style.height = "auto";
  };
  return (
    <form
      data-testid="composer"
      className="flex w-full flex-col gap-1.5 rounded-2xl p-2"
      style={{ background: "var(--hub-card-bg)", border: "1px solid var(--border-default)", boxShadow: "var(--glass-shadow-hover)", outline: dragging ? "2px dashed var(--accent)" : undefined }}
      onSubmit={(e) => { e.preventDefault(); void submit(); }}
      onDragOver={(e) => { if (!disabled && e.dataTransfer?.types?.includes("Files")) { e.preventDefault(); setDragging(true); } }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { setDragging(false); if (disabled) return; e.preventDefault(); addFiles(Array.from(e.dataTransfer?.files ?? [])); }}
    >
      {files.length > 0 && (
        <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0" aria-label="Attached files" data-testid="attached-files">
          {files.map((f, i) => {
            const st = fileStatus?.(f);
            return (
              <li key={`${f.name}-${f.size}-${f.lastModified}`} data-testid="attached-file" data-status={st ?? "selected"} className="flex items-center gap-1.5 rounded-lg px-2 py-1 t-meta" style={{ border: `1px solid ${st === "failed" ? "var(--negative)" : "var(--border-subtle)"}`, color: "var(--text-3)" }}>
                <span className="max-w-[12rem] truncate">{f.name}</span>
                <span style={{ color: "var(--text-5)" }}>{sizeOf(f.size)}</span>
                {fileInfo?.(f) && <span data-testid="file-info" style={{ color: "var(--text-4)" }}>{fileInfo(f)}</span>}
                {st && <span role="status" style={{ color: st === "failed" ? "var(--negative)" : st === "uploaded" ? "var(--accent)" : "var(--text-4)" }}>{STATUS_WORDS[st]}</span>}
                <button type="button" disabled={sending} aria-label={`Remove ${f.name}`} onClick={() => setFiles((fs) => fs.filter((_, j) => j !== i))} className="mt-focus" style={{ color: "var(--text-5)" }}>
                  <Icon name="close" size={12} />
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {files.some((f) => /\.(csv|xlsx)$/i.test(f.name)) && (
        <p className="m-0 t-meta" data-testid="report-handoff" style={{ color: "var(--text-4)" }}>
          Your CEO can read attached spreadsheets and analyze their contents in this conversation. For persistent financial records and formal marketplace reconciliation, use{" "}
          <Link href="/dashboard/cfo" className="mt-focus font-semibold underline" style={{ color: "var(--text-2)" }}>Profit &amp; Finance</Link>.
        </p>
      )}
      {files.some((f) => f.type.startsWith("image/")) && (
        <p className="m-0 t-meta" data-testid="image-handoff" style={{ color: "var(--text-4)" }}>
          Attach a competitor&apos;s listing or reviews screenshot and say which competitor it shows, for example “this is The Better Home 1L”. The CEO reads it and asks you to confirm the price, discount, delivery and offers before anything is used. A product photo is read only after you approve. Results appear on the{" "}
          <Link href="/dashboard/competitors" className="mt-focus font-semibold underline" style={{ color: "var(--text-2)" }}>Competitors page</Link>.
        </p>
      )}
      {error && <div role="alert" className="t-meta" style={{ color: "var(--negative)" }}>{error}</div>}
      <div className="flex items-end gap-1.5 rounded-2xl py-1.5 pl-1.5 pr-1.5 transition-colors focus-within:[border-color:var(--accent-border-strong)]" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border-default)" }}>
        <input ref={picker} type="file" multiple accept={ACCEPT} className="hidden" data-testid="file-input" aria-label="Attach files" onChange={(e) => { addFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
        <button type="button" disabled={disabled || sending} aria-label="Attach a file" title="Attach images, PDFs, CSV or Excel files" onClick={() => picker.current?.click()} className="mt-btn mt-focus flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl" style={{ color: "var(--text-4)", opacity: disabled ? 0.45 : 1 }}>
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M21 11.5l-8.6 8.6a5.5 5.5 0 0 1-7.8-7.8l8.9-8.9a3.7 3.7 0 0 1 5.2 5.2l-8.9 8.9a1.8 1.8 0 0 1-2.6-2.6l8.2-8.2" /></svg>
        </button>
        <textarea
          ref={box}
          value={text}
          onChange={(e) => { setText(e.target.value); e.target.style.height = "auto"; e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`; }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
          }}
          rows={1}
          maxLength={4000}
          disabled={disabled}
          aria-label="Ask the CEO"
          placeholder={placeholder}
          className="mt-focus max-h-40 min-h-[40px] min-w-0 flex-1 resize-none bg-transparent px-1 py-2.5 t-body outline-none"
          style={{ color: "var(--text-1)" }}
        />
        <button
          type="submit" disabled={!canSend} aria-label="Send"
          className="mt-btn mt-focus flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl transition-opacity"
          style={{ background: "var(--accent)", color: "var(--accent-on-fill)", opacity: canSend ? 1 : 0.35 }}
        >
          {disabled || sending ? <Spinner /> : <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M12 19V5" /><path d="M5 12l7-7 7 7" /></svg>}
        </button>
      </div>
      <div className="px-1.5 t-meta" style={{ color: "var(--text-6)" }}>Enter to send · Shift+Enter for a new line · Drop files to attach</div>
    </form>
  );
}
