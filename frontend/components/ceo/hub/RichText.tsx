import { Fragment, type ReactNode } from "react";

/** Renders the CEO's answer with a tiny, fixed markup the backend writes by code (never user input): "## " / "### " headings, "- " bullets, **bold** and
 * [label](https://...) links. No HTML is ever interpreted: every piece becomes a React node, a link is shown only for an http(s) address, and plain text without markup renders
 * exactly as before (line breaks kept). Links open in a new tab and are bold and underlined so the important ones are easy to see. */
const INLINE = /(\*\*[^*]+\*\*|\[[^\]]+\]\(https?:\/\/[^)\s]+\))/g;

function inline(text: string, keyBase: string): ReactNode[] {
  return text.split(INLINE).filter((p) => p !== "").map((part, i) => {
    const key = `${keyBase}-${i}`;
    const bold = /^\*\*([^*]+)\*\*$/.exec(part);
    if (bold) return <strong key={key} style={{ color: "var(--text-1)", fontWeight: 700 }}>{bold[1]}</strong>;
    const link = /^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/.exec(part);
    if (link) {
      return (
        <a key={key} href={link[2]} target="_blank" rel="noopener noreferrer" className="font-bold underline underline-offset-2" style={{ color: "var(--accent)", fontSize: "1.04em" }}>
          {link[1]}
        </a>
      );
    }
    return <Fragment key={key}>{part}</Fragment>;
  });
}

export function RichText({ text }: { text: string }) {
  const lines = text.split("\n");
  const out: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = (at: number) => {
    if (bullets.length === 0) return;
    out.push(
      <ul key={`ul-${at}`} className="my-1 flex list-disc flex-col gap-1 pl-5">
        {bullets.map((b, i) => <li key={i}>{inline(b, `li-${at}-${i}`)}</li>)}
      </ul>,
    );
    bullets = [];
  };
  lines.forEach((line, i) => {
    if (line.startsWith("- ")) {
      bullets.push(line.slice(2));
      return;
    }
    flush(i);
    if (line.startsWith("### ")) {
      out.push(<h4 key={i} className="mb-0.5 mt-3 t-body font-bold" style={{ color: "var(--accent)" }}>{inline(line.slice(4), `h4-${i}`)}</h4>);
    } else if (line.startsWith("## ")) {
      out.push(<h3 key={i} className="mb-1 t-card-title font-bold" style={{ color: "var(--text-1)" }}>{inline(line.slice(3), `h3-${i}`)}</h3>);
    } else if (line.trim() === "") {
      out.push(<div key={i} className="h-1.5" aria-hidden />);
    } else {
      out.push(<p key={i} className="m-0 whitespace-pre-wrap">{inline(line, `p-${i}`)}</p>);
    }
  });
  flush(lines.length);
  return <>{out}</>;
}
