"use client";

import { Icon, type IconName } from "@/components/ui/Icon";
import type { AgentCode, UiAction } from "@/lib/ceo";
import { QUICK_ACTIONS, quickActionState } from "@/lib/ceoModel";

const QUESTIONS = ["Why did my profit drop?", "Am I being paid what I am owed?", "Give me my business briefing", "What should I focus on this month?"];
const GROUPS: { title: string; icon: IconName; ids: string[] }[] = [
  { title: "My business", icon: "finance", ids: ["pnl", "bands", "leaks", "gaps", "briefing"] },
  { title: "Competitors and products", icon: "competitors", ids: ["competitors", "research", "report", "listing"] },
  { title: "Checks", icon: "check", ids: ["diagnosis", "anomaly"] },
];

/** The empty conversation: what the CEO can do, as things to click. Each tile is one catalog item (no model decides what it meant); a period or any other
 * missing input is asked for in the conversation, never guessed. */
export function Welcome({
  agents, onAsk, onAction, onOpenForm,
}: { agents: Partial<Record<AgentCode, boolean>> | null; onAsk: (text: string) => void; onAction: (label: string, action: UiAction) => void; onOpenForm: (form: string) => void }) {
  return (
    <div className="mx-auto flex w-full max-w-[760px] flex-col gap-6 py-6" data-testid="welcome">
      <div className="text-center">
        <span className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl" style={{ background: "var(--fill-hover)", color: "var(--accent)" }}>
          <Icon name="ceo" size={24} />
        </span>
        <h2 className="m-0 t-card-title font-bold" style={{ color: "var(--text-1)" }}>What would you like to know?</h2>
        <p className="mx-auto mt-2 max-w-[520px] t-body-sm" style={{ color: "var(--text-5)" }}>
          Ask in your own words. I answer from your saved results, hand the question to the right agent when one owns it, and ask you for anything I am missing.
        </p>
      </div>

      <div className="flex flex-wrap justify-center gap-2" role="group" aria-label="Question ideas">
        {QUESTIONS.map((q) => (
          <button key={q} type="button" onClick={() => onAsk(q)} className="mt-chip mt-focus rounded-full px-3 py-1.5 t-body-sm" style={{ color: "var(--text-3)", border: "1px solid var(--border-subtle)" }}>
            {q}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3" data-testid="quick-actions">
        {GROUPS.map((g) => (
          <section key={g.title} className="flex flex-col gap-1.5 rounded-2xl p-3" style={{ border: "1px solid var(--border-subtle)", background: "var(--bg-card)" }}>
            <h3 className="m-0 flex items-center gap-1.5 t-meta font-bold uppercase tracking-wide" style={{ color: "var(--text-5)" }}>
              <Icon name={g.icon} size={13} /> {g.title}
            </h3>
            {QUICK_ACTIONS.filter((qa) => g.ids.includes(qa.id)).map((qa) => {
              const s = quickActionState(qa, agents, qa.needsPeriod ? { start: "x", end: "x" } : null); // a period is asked for in the conversation, so it never blocks a tile
              return (
                <button
                  key={qa.id} type="button" data-testid={`quick-${qa.id}`} disabled={!s.enabled} title={s.reason ?? undefined}
                  onClick={() => onAction(qa.label, qa.action)}
                  className="mt-btn mt-focus rounded-lg px-2.5 py-1.5 text-left t-body-sm" style={{ color: "var(--text-2)", opacity: s.enabled ? 1 : 0.45 }}
                >
                  {qa.label}
                </button>
              );
            })}
          </section>
        ))}
      </div>

      <div className="flex flex-wrap justify-center gap-2" role="group" aria-label="Decide">
        <button type="button" data-testid="start-price-impact" onClick={() => onAction("A competitor changed their price", { kind: "PLAYBOOK", key: "COMPETITOR_PRICE_IMPACT" })} className="mt-chip mt-focus rounded-xl px-3.5 py-2 t-body-sm font-semibold" style={{ color: "var(--text-2)", border: "1px solid var(--accent-border-default)" }}>
          A competitor changed their price
        </button>
        <button type="button" data-testid="start-new-product" onClick={() => onAction("Should I stock a new product?", { kind: "PLAYBOOK", key: "NEW_PRODUCT_DECISION" })} className="mt-chip mt-focus rounded-xl px-3.5 py-2 t-body-sm font-semibold" style={{ color: "var(--text-2)", border: "1px solid var(--accent-border-default)" }}>
          Should I stock a new product?
        </button>
      </div>
      <p className="m-0 text-center t-meta" style={{ color: "var(--text-6)" }}>
        Saved inputs:{" "}
        <button type="button" data-testid="open-price-impact" onClick={() => onOpenForm("COMPETITOR_PRICE_IMPACT")} className="mt-focus underline" style={{ color: "var(--text-4)" }}>cost per unit</button>
        {" · "}
        <button type="button" data-testid="open-new-product" onClick={() => onOpenForm("NEW_PRODUCT_DECISION")} className="mt-focus underline" style={{ color: "var(--text-4)" }}>supplier quotes and budget</button>
      </p>
    </div>
  );
}
