"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingState } from "@/components/ui/LoadingState";
import { Section } from "@/components/ui/Section";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ProblemNotice, SubmitButton, TextInput, useAction } from "@/components/cmo/shared";
import { useCmoSession } from "@/components/cmo/session";
import { cmo, explainCmoError, type CmoProblem, type NicheConfirmResponse, type NicheSuggestResponse, type NicheTerm } from "@/lib/cmo";

const ORIGIN: Record<string, string> = { CATALOG_DERIVED: "From your catalog titles", SELLER_STATED: "You typed it", SELLER_FACT: "From a category you gave" };

/** Only niche terms YOU confirm are ever used for market research — nothing else about your business leaves Metrion. Suggestions come
 * from your own catalog titles (no search, no model) and stay suggestions until you confirm, edit or reject them. */
export function NicheTab() {
  const { getToken } = useAuth();
  const { record } = useCmoSession();
  const [terms, setTerms] = useState<NicheTerm[] | null>(null);
  const [loadProblem, setLoadProblem] = useState<CmoProblem | null>(null);
  const suggest = useAction<NicheSuggestResponse>();
  const apply = useAction<NicheConfirmResponse>();
  const [typed, setTyped] = useState("");
  const [edits, setEdits] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      setTerms((await cmo.listNiche(getToken)).terms);
      setLoadProblem(null);
    } catch (e) {
      setLoadProblem(explainCmoError(e));
    }
  }, [getToken]);
  useEffect(() => {
    (async () => {
      await load();
    })();
  }, [load]);

  const doSuggest = async () => {
    const r = await suggest.run(() => cmo.suggestNiche(getToken));
    if (r) {
      record("Niche suggestions", 0);
      await load();
    }
  };
  const decide = async (decisions: { term_id: string; decision: "CONFIRM" | "REJECT" | "EDIT"; new_text?: string }[], newTerms: string[] = []) => {
    const r = await apply.run(() => cmo.confirmNiche(getToken, decisions, newTerms));
    if (r) {
      record("Niche terms updated", 0);
      setTyped("");
      setEdits({});
      await load();
    }
  };

  const confirmed = (terms ?? []).filter((t) => t.status === "CONFIRMED");
  const suggested = (terms ?? []).filter((t) => t.status === "SUGGESTED");
  const rejected = (terms ?? []).filter((t) => t.status === "REJECTED");

  return (
    <div className="mt-stack">
      <Section
        title="Your niche terms"
        hint="These words describe what you sell. Only confirmed terms are used when Metrion researches the market — never your sales, customers or costs."
        action={<SubmitButton onClick={doSuggest} busy={suggest.busy} label="Suggest from my catalog" busyLabel="Reading titles…" />}
      >
        <ProblemNotice problem={loadProblem} onRetry={load} />
        <ProblemNotice problem={suggest.problem} onRetry={doSuggest} />
        <ProblemNotice problem={apply.problem} />
        {suggest.result?.status === "UNAVAILABLE" && (
          <div role="status" className="mb-3 t-body-sm" style={{ color: "var(--warning)" }}>{suggest.result.reason}</div>
        )}
        {terms === null && !loadProblem && <LoadingState lines={3} label="Loading your niche terms" />}
        {terms !== null && confirmed.length === 0 && <EmptyState compact icon="check" title="No confirmed terms yet" description="Confirm a suggestion below, or type your own. Market research needs at least one for the niche sections." />}
        {confirmed.length > 0 && (
          <ul className="flex flex-wrap gap-2" aria-label="Confirmed niche terms">
            {confirmed.map((t) => (
              <li key={t.id} className="flex items-center gap-2 rounded-lg px-2.5 py-1" style={{ background: "var(--accent-fill-default)", border: "1px solid var(--accent-border-subtle)", color: "var(--accent)" }}>
                <span className="t-body-sm font-semibold">{t.term}</span>
                <button type="button" aria-label={`Stop using ${t.term}`} className="mt-focus t-meta font-bold underline" disabled={apply.busy} onClick={() => decide([{ term_id: t.id, decision: "REJECT" }])}>
                  remove
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-4 flex flex-wrap items-end gap-2">
          <div className="min-w-[14rem] flex-1">
            <label className="mb-1 block t-body-sm" style={{ color: "var(--text-6)" }} htmlFor="niche-typed">Type a niche term</label>
            <TextInput id="niche-typed" value={typed} onChange={setTyped} placeholder="e.g. steel water bottle" maxLength={200} />
          </div>
          <SubmitButton onClick={() => decide([], [typed])} busy={apply.busy} label="Add and confirm" busyLabel="Saving…" disabled={!typed.trim()} />
        </div>
        <div className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>Terms cannot contain phone numbers, e-mail or web addresses, tax or order numbers.</div>
      </Section>

      {suggested.length > 0 && (
        <Section title="Suggestions" hint="Words that appear in your own catalog titles. Check each one — a brand name or a word that is not your niche should be rejected.">
          <ul className="flex flex-col gap-2">
            {suggested.map((t) => {
              const draft = edits[t.id];
              return (
                <li key={t.id} className="rounded-xl px-3 py-2.5" style={{ border: "1px solid var(--border-hover)" }}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="t-body font-semibold" style={{ color: "var(--text-2)" }}>{t.term}</span>
                    <StatusBadge tone="neutral">{ORIGIN[t.origin] ?? t.origin}</StatusBadge>
                    {t.documentFrequency != null && <StatusBadge tone="neutral">in {t.documentFrequency} titles</StatusBadge>}
                  </div>
                  {t.originNote && <div className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>{t.originNote}</div>}
                  <div className="mt-2 flex flex-wrap items-end gap-2">
                    <SubmitButton primary busy={apply.busy} busyLabel="Saving…" label="Confirm" onClick={() => decide([{ term_id: t.id, decision: "CONFIRM" }])} />
                    <SubmitButton busy={apply.busy} busyLabel="Saving…" label="Reject" onClick={() => decide([{ term_id: t.id, decision: "REJECT" }])} />
                    <div className="min-w-[12rem] flex-1">
                      <TextInput value={draft ?? ""} onChange={(v) => setEdits((e) => ({ ...e, [t.id]: v }))} placeholder="Or reword it…" maxLength={200} />
                    </div>
                    <SubmitButton busy={apply.busy} busyLabel="Saving…" label="Use my wording" disabled={!draft?.trim()} onClick={() => decide([{ term_id: t.id, decision: "EDIT", new_text: draft!.trim() }])} />
                  </div>
                </li>
              );
            })}
          </ul>
        </Section>
      )}
      {rejected.length > 0 && (
        <div className="t-meta" style={{ color: "var(--text-6)" }}>
          {rejected.length} rejected term{rejected.length === 1 ? "" : "s"} will not be suggested again.
        </div>
      )}
    </div>
  );
}
