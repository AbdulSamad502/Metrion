"use client";

import { useRef, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { Spinner } from "@/components/ui/LoadingState";

const ACCEPT = ".png,.jpg,.jpeg,.webp,.pdf,.csv,.xlsx";

/** The chat bar: always at the bottom. Whatever the CEO or an agent asks, the answer is typed here (the backend parses it against the one question that
 * was asked). Enter sends, Shift+Enter adds a line. Files are attached with the + button; their type is decided by the backend from the content. */
export function Composer({
  disabled, placeholder, onSend, error,
}: { disabled: boolean; placeholder: string; onSend: (text: string, files: File[]) => void; error?: string | null }) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const picker = useRef<HTMLInputElement | null>(null);
  const canSend = !disabled && (text.trim().length > 0 || files.length > 0);
  const submit = () => {
    if (!canSend) return;
    onSend(text.trim(), files);
    setText("");
    setFiles([]);
  };
  return (
    <form
      data-testid="composer"
      className="mx-auto flex w-full max-w-[1100px] flex-col gap-2 rounded-2xl px-3.5 py-2.5"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border-hover)", boxShadow: "var(--glass-shadow-hover)" }}
      onSubmit={(e) => { e.preventDefault(); submit(); }}
    >
      {files.length > 0 && (
        <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0" aria-label="Attached files" data-testid="attached-files">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex items-center gap-1.5 rounded-lg px-2 py-1 t-meta" style={{ border: "1px solid var(--border-subtle)", color: "var(--text-3)" }}>
              {f.name}
              <button type="button" aria-label={`Remove ${f.name}`} onClick={() => setFiles((fs) => fs.filter((_, j) => j !== i))} className="mt-focus" style={{ color: "var(--text-5)" }}>
                <Icon name="close" size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <div role="alert" className="t-meta" style={{ color: "var(--negative)" }}>{error}</div>}
      <div className="flex items-end gap-2.5">
        <input ref={picker} type="file" multiple accept={ACCEPT} className="hidden" data-testid="file-input" aria-label="Attach files" onChange={(e) => { setFiles((fs) => [...fs, ...Array.from(e.target.files ?? [])]); e.target.value = ""; }} />
        <button type="button" disabled={disabled} aria-label="Attach a file" title="Attach images, PDFs, CSV or Excel files" onClick={() => picker.current?.click()} className="mt-btn mt-focus flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl" style={{ border: "1px solid var(--border-subtle)", color: "var(--text-3)", opacity: disabled ? 0.45 : 1 }}>
          <Icon name="plus" size={16} />
        </button>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={1}
          maxLength={4000}
          disabled={disabled}
          aria-label="Ask the CEO"
          placeholder={placeholder}
          className="mt-focus max-h-40 min-h-[40px] min-w-0 flex-1 resize-none bg-transparent py-2 t-body outline-none"
          style={{ color: "var(--text-2)" }}
        />
        <button
          type="submit" disabled={!canSend} aria-label="Send"
          className="mt-btn mt-focus flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl"
          style={{ background: "var(--accent)", color: "var(--accent-on-fill)", opacity: canSend ? 1 : 0.45 }}
        >
          {disabled ? <Spinner /> : <Icon name="arrow" size={16} />}
        </button>
      </div>
    </form>
  );
}
