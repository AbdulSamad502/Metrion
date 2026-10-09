"use client";

import { useEffect, useState } from "react";
import { CostInput } from "@/components/ui/CostInput";
import { ApiError } from "@/lib/api";
import type { CeoClient, CostValue, NewProductFormSupport, PriceImpactFormSupport, UiAction } from "@/lib/ceo";
import { costReady, costToApi, EMPTY_COST, parseCount, rupeesToPaise, type CostChoice } from "@/lib/costInput";

export type DecideKind = "COMPETITOR_PRICE_IMPACT" | "NEW_PRODUCT_DECISION";
type Run = (label: string, action: UiAction) => void;

const box = { border: "1px solid var(--border-subtle)", background: "var(--bg-card)" } as const;
const inputCls = "mt-input w-full rounded-lg px-3 py-2 t-body";
const btn = "mt-btn mt-focus rounded-lg px-3 py-1.5 t-body-sm font-bold";

function Lbl({ text, children }: { text: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 t-body-sm" style={{ color: "var(--text-5)" }}>
      {text}
      {children}
    </label>
  );
}

const asCost = (c: CostChoice): CostValue => {
  const { paise, reason } = costToApi(c);
  if (c.mode === "unknown") return { state: "UNKNOWN", reason };
  return c.mode === "none" ? { state: "NONE_CONFIRMED" } : { state: "AMOUNT", amount_paise: paise as number };
};

/** The two decision playbooks' run-forms (spec 6.33). Prices and costs are entered HERE, never typed into chat. Each cost is answered explicitly; stored values are
 * shown with their dates; saving writes through the existing CFO expense path. Nothing is computed in the browser: the form sends integer paise and the backend runs. */
export function DecidePanel({ client, kind, disabled, onRun, onClose }: { client: CeoClient; kind: DecideKind; disabled: boolean; onRun: Run; onClose: () => void }) {
  return (
    <section aria-label={kind === "COMPETITOR_PRICE_IMPACT" ? "Price impact" : "New product"} data-testid="decide-panel" className="flex flex-col gap-3 rounded-2xl px-4 py-3" style={box}>
      <div className="flex items-center justify-between">
        <h3 className="t-card-title m-0 font-semibold" style={{ color: "var(--text-1)" }}>
          {kind === "COMPETITOR_PRICE_IMPACT" ? "A competitor changed their price" : "Should I stock a new product?"}
        </h3>
        <button type="button" onClick={onClose} className={btn} style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}>Close</button>
      </div>
      {kind === "COMPETITOR_PRICE_IMPACT" ? <PriceImpactForm client={client} disabled={disabled} onRun={onRun} /> : <NewProductForm client={client} disabled={disabled} onRun={onRun} />}
    </section>
  );
}

function useSaveError() {
  const [msg, setMsg] = useState<string | null>(null);
  const fail = (e: unknown) => setMsg(e instanceof ApiError && e.status === 403 ? "You do not have permission to save this." : "Could not save. Nothing was changed.");
  return { msg, setMsg, fail };
}

function PriceImpactForm({ client, disabled, onRun }: { client: CeoClient; disabled: boolean; onRun: Run }) {
  const [support, setSupport] = useState<PriceImpactFormSupport | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [competitor, setCompetitor] = useState("");
  const [sku, setSku] = useState("");
  const [fee, setFee] = useState("");
  const [basis, setBasis] = useState<"INCLUSIVE" | "EXCLUSIVE">("INCLUSIVE");
  const [gst, setGst] = useState("");
  const [current, setCurrent] = useState("");
  const [prices, setPrices] = useState<string[]>([""]);
  const [costs, setCosts] = useState<Record<"shipping" | "advertising" | "return_rto" | "other", CostChoice>>({ shipping: EMPTY_COST, advertising: EMPTY_COST, return_rto: EMPTY_COST, other: EMPTY_COST });
  const [newCost, setNewCost] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const { msg, setMsg, fail } = useSaveError();

  useEffect(() => {
    client.getPriceImpactForm().then(setSupport, () => setLoadError(true));
  }, [client]);
  const refreshCost = (s: string) => client.getPriceImpactForm(s.trim() || undefined).then((r) => setSupport((p) => (p ? { ...p, storedCost: r.storedCost } : r)), () => undefined);

  if (loadError) return <p role="alert" className="t-body-sm" style={{ color: "var(--negative)" }}>Could not load this form. You may not have access to the CFO data it needs.</p>;
  if (!support) return <p className="t-body-sm">Loading…</p>;
  const max = support.maxCandidatePrices;
  const cost = support.storedCost;

  const run = () => {
    const [marketplace, category, feeType] = fee.split("|");
    const currentPaise = rupeesToPaise(current);
    const list = prices.map((p) => rupeesToPaise(p));
    if (!competitor || !sku.trim() || !fee) return setProblem("Choose a competitor, enter the SKU and choose a marketplace / category / fee type.");
    if (currentPaise === null || currentPaise === 0) return setProblem("Enter your current price in rupees, for example 499.");
    if (list.some((p) => p === null || p === 0)) return setProblem("Every candidate price must be a rupee amount above zero.");
    if (new Set(list).size !== list.length) return setProblem("Candidate prices must all be different.");
    if (!Object.values(costs).every(costReady)) return setProblem("Answer every cost: an amount, “None (0), I confirm”, or Unknown. Nothing is assumed to be zero.");
    setProblem(null);
    onRun("Price impact", {
      kind: "PLAYBOOK", key: "COMPETITOR_PRICE_IMPACT",
      inputs: {
        competitor_url_id: competitor, sku: sku.trim(), marketplace, category, fee_type: feeType, basis, gst_rate_pct: gst.trim() || null, current_price_paise: currentPaise,
        candidate_prices_paise: list, shipping: asCost(costs.shipping), advertising: asCost(costs.advertising), return_rto: asCost(costs.return_rto), other: asCost(costs.other),
      },
    });
  };

  const saveCost = async () => {
    const paise = rupeesToPaise(newCost);
    if (!sku.trim() || paise === null) return setMsg("Enter the SKU and a cost in rupees first.");
    try {
      await client.saveInput({ target_type: "SKU", target_ref: sku.trim(), field: "cogs_per_unit", value: { amount_paise: paise, effective_from: new Date().toISOString().slice(0, 10) } });
      setMsg(null);
      setSaved("Cost saved.");
      setNewCost("");
      await refreshCost(sku);
    } catch (e) {
      fail(e);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Lbl text="Competitor">
          <select aria-label="Competitor" className={inputCls} value={competitor} onChange={(e) => setCompetitor(e.target.value)}>
            <option value="">Choose…</option>
            {support.competitors.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
        </Lbl>
        <Lbl text="SKU">
          <input aria-label="SKU" className={inputCls} value={sku} onChange={(e) => setSku(e.target.value)} onBlur={() => void refreshCost(sku)} />
        </Lbl>
        <Lbl text="Marketplace / category / fee type">
          <select aria-label="Fee reference" className={inputCls} value={fee} onChange={(e) => setFee(e.target.value)}>
            <option value="">Choose…</option>
            {support.feeOptions.map((o) => <option key={`${o.marketplace}|${o.category}|${o.feeType}`} value={`${o.marketplace}|${o.category}|${o.feeType}`}>{o.marketplace} · {o.category} · {o.feeType}</option>)}
          </select>
        </Lbl>
        <Lbl text="Prices include GST?">
          <select aria-label="Price basis" className={inputCls} value={basis} onChange={(e) => setBasis(e.target.value as "INCLUSIVE" | "EXCLUSIVE")}>
            <option value="INCLUSIVE">Yes, inclusive</option>
            <option value="EXCLUSIVE">No, exclusive</option>
          </select>
        </Lbl>
        <Lbl text="GST rate % (optional; blank stays unavailable)">
          <input aria-label="GST rate" className={inputCls} value={gst} onChange={(e) => setGst(e.target.value)} placeholder="e.g. 18" />
        </Lbl>
        <Lbl text="Your current selling price (rupees)">
          <input aria-label="Current price" inputMode="decimal" className={inputCls} value={current} onChange={(e) => setCurrent(e.target.value)} />
        </Lbl>
      </div>

      <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
        <legend className="p-0 t-body-sm font-medium" style={{ color: "var(--text-5)" }}>
          Candidate prices to compare (rupees){max === null ? "" : `, up to ${max}`}
        </legend>
        {max === null && <p role="alert" className="t-meta" style={{ color: "var(--warning)" }}>The limit on candidate prices has not been configured by the operator, so this cannot run yet.</p>}
        {prices.map((p, i) => (
          <div key={i} className="flex gap-2">
            <input aria-label={`Candidate price ${i + 1}`} inputMode="decimal" className={inputCls} value={p} onChange={(e) => setPrices((ps) => ps.map((x, j) => (j === i ? e.target.value : x)))} />
            {prices.length > 1 && <button type="button" className={btn} onClick={() => setPrices((ps) => ps.filter((_, j) => j !== i))} style={{ border: "1px solid var(--border-hover)" }}>Remove</button>}
          </div>
        ))}
        {max !== null && prices.length < max && <button type="button" className={`${btn} w-fit`} style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }} onClick={() => setPrices((ps) => [...ps, ""])}>+ Add a price</button>}
      </fieldset>

      <div className="rounded-lg px-3 py-2 t-body-sm" style={{ border: "1px dashed var(--border-subtle)", color: "var(--text-3)" }} data-testid="stored-cost">
        {cost && cost.formatted
          ? <>Your saved cost per unit for this SKU: <strong>{cost.formatted}</strong>{cost.effectiveFrom ? `, effective ${cost.effectiveFrom}` : ""}. It will be used unless you save a new one.</>
          : <>No saved cost per unit{sku.trim() ? " for this SKU" : ""}: margins will be shown as unavailable until you save one.</>}
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <Lbl text="Save a new cost per unit (rupees)"><input aria-label="New cost per unit" inputMode="decimal" className={inputCls} value={newCost} onChange={(e) => setNewCost(e.target.value)} /></Lbl>
          <button type="button" className={btn} onClick={() => void saveCost()} style={{ border: "1px solid var(--border-hover)", color: "var(--text-2)" }}>Save cost</button>
          {saved && <span role="status" className="t-meta">{saved}</span>}
        </div>
        {msg && <div role="alert" className="mt-1 t-meta" style={{ color: "var(--negative)" }}>{msg}</div>}
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <CostInput label="Shipping per unit" value={costs.shipping} onChange={(c) => setCosts((s) => ({ ...s, shipping: c }))} />
        <CostInput label="Advertising per unit" value={costs.advertising} onChange={(c) => setCosts((s) => ({ ...s, advertising: c }))} />
        <CostInput label="Return and RTO losses per unit" value={costs.return_rto} onChange={(c) => setCosts((s) => ({ ...s, return_rto: c }))} />
        <CostInput label="Other costs per unit" value={costs.other} onChange={(c) => setCosts((s) => ({ ...s, other: c }))} />
      </div>
      {problem && <div role="alert" className="t-body-sm" style={{ color: "var(--negative)" }}>{problem}</div>}
      <button type="button" disabled={disabled || max === null} onClick={run} className={`${btn} self-start`} style={{ background: "var(--accent)", color: "var(--accent-on-fill)", opacity: disabled || max === null ? 0.5 : 1 }}>
        Run price impact
      </button>
    </div>
  );
}

function NewProductForm({ client, disabled, onRun }: { client: CeoClient; disabled: boolean; onRun: Run }) {
  const [sku, setSku] = useState("");
  const [qty, setQty] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [stored, setStored] = useState<NewProductFormSupport>({ quotes: [], budget: [], budgetTargetRef: "" });
  const [q, setQ] = useState({ name: "", unit: "", ship: "", duties: "", moq: "", lead: "" });
  const [budget, setBudget] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const { msg, setMsg, fail } = useSaveError();

  const reload = (s: string) => client.getNewProductForm(s.trim() || undefined).then(setStored, () => undefined);
  useEffect(() => {
    void reload("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);
  const today = new Date().toISOString().slice(0, 10);

  const saveQuote = async () => {
    const unit = rupeesToPaise(q.unit);
    const opt = (v: string) => (v.trim() === "" ? undefined : rupeesToPaise(v));
    const ship = opt(q.ship), duties = opt(q.duties);
    const moq = q.moq.trim() === "" ? undefined : parseCount(q.moq);
    const lead = q.lead.trim() === "" ? undefined : parseCount(q.lead);
    if (!sku.trim() || !q.name.trim() || unit === null || ship === null || duties === null || moq === null || lead === null) return setMsg("Enter the SKU, supplier name and a unit cost; shipping, duties, MOQ and lead time must be plain numbers if you fill them in.");
    const value: Record<string, unknown> = { supplier_name: q.name.trim(), unit_cost_paise: unit };
    if (ship !== undefined) value.shipping_paise = ship;
    if (duties !== undefined) value.duties_paise = duties;
    if (moq !== undefined) value.moq = moq;
    if (lead !== undefined) value.lead_time_days = lead;
    try {
      // A single saved quote is replaced (superseded), so the engine is never left with two to choose between. Several: the seller sees them listed and decides.
      await client.saveInput({ target_type: "SKU", target_ref: sku.trim(), field: "supplier.quote", value, supersedes_id: stored.quotes.length === 1 ? stored.quotes[0].id : null });
      setMsg(null); setSaved("Quote saved."); await reload(sku);
    } catch (e) { fail(e); }
  };
  const saveBudget = async () => {
    const paise = rupeesToPaise(budget);
    if (!stored.budgetTargetRef) return setMsg("The budget form is still loading.");
    if (paise === null || paise === 0) return setMsg("Enter a budget in rupees above zero.");
    try {
      await client.saveInput({ target_type: "ACCOUNT", target_ref: stored.budgetTargetRef, field: "batch.budget", value: { amount_paise: paise }, supersedes_id: stored.budget.length === 1 ? stored.budget[0].id : null });
      setMsg(null); setSaved("Budget saved."); setBudget(""); await reload(sku);
    } catch (e) { fail(e); }
  };

  const run = () => {
    const units = parseCount(qty);
    if (!sku.trim() || units === null || units < 1) return setProblem("Enter the SKU and how many units you are considering.");
    if (!start || !end || end < start || end > today) return setProblem("Choose a sales-history period that has ended.");
    setProblem(null);
    onRun("New product decision", { kind: "PLAYBOOK", key: "NEW_PRODUCT_DECISION", inputs: { sku: sku.trim(), quantity: units, period_start: start, period_end: end } });
  };
  const show = (r: { id: string; createdAt: string; summary: string }) => (
    <li key={r.id} className="t-body-sm">
      {r.summary}, saved {r.createdAt.slice(0, 10)}
    </li>
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Lbl text="SKU"><input aria-label="SKU" className={inputCls} value={sku} onChange={(e) => setSku(e.target.value)} onBlur={() => void reload(sku)} /></Lbl>
        <Lbl text="Units you are considering"><input aria-label="Quantity" inputMode="numeric" className={inputCls} value={qty} onChange={(e) => setQty(e.target.value)} /></Lbl>
        <Lbl text="Sales history from"><input aria-label="History from" type="date" max={today} className={inputCls} value={start} onChange={(e) => setStart(e.target.value)} /></Lbl>
        <Lbl text="Sales history to"><input aria-label="History to" type="date" max={today} className={inputCls} value={end} onChange={(e) => setEnd(e.target.value)} /></Lbl>
      </div>
      <div className="rounded-lg px-3 py-2" style={{ border: "1px dashed var(--border-subtle)" }} data-testid="stored-quotes">
        <div className="t-body-sm font-medium" style={{ color: "var(--text-3)" }}>Saved supplier quotes for this SKU</div>
        {stored.quotes.length ? <ul className="m-0 list-none p-0">{stored.quotes.map((r) => show(r))}</ul> : <p className="m-0 t-body-sm">None saved: landed cost and batch size will ask for one.</p>}
        {stored.quotes.length > 1 && <p role="status" className="m-0 t-meta" style={{ color: "var(--warning)" }}>More than one quote is active, so the analysis will ask which to use instead of picking.</p>}
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Lbl text="Supplier"><input aria-label="Supplier name" className={inputCls} value={q.name} onChange={(e) => setQ({ ...q, name: e.target.value })} /></Lbl>
          <Lbl text="Unit cost (rupees)"><input aria-label="Unit cost" inputMode="decimal" className={inputCls} value={q.unit} onChange={(e) => setQ({ ...q, unit: e.target.value })} /></Lbl>
          <Lbl text="Shipping, whole order (rupees)"><input aria-label="Shipping" inputMode="decimal" className={inputCls} value={q.ship} onChange={(e) => setQ({ ...q, ship: e.target.value })} /></Lbl>
          <Lbl text="Duties, whole order (rupees)"><input aria-label="Duties" inputMode="decimal" className={inputCls} value={q.duties} onChange={(e) => setQ({ ...q, duties: e.target.value })} /></Lbl>
          <Lbl text="Minimum order (units)"><input aria-label="MOQ" inputMode="numeric" className={inputCls} value={q.moq} onChange={(e) => setQ({ ...q, moq: e.target.value })} /></Lbl>
          <Lbl text="Lead time (days)"><input aria-label="Lead time" inputMode="numeric" className={inputCls} value={q.lead} onChange={(e) => setQ({ ...q, lead: e.target.value })} /></Lbl>
        </div>
        <button type="button" className={`${btn} mt-2`} onClick={() => void saveQuote()} style={{ border: "1px solid var(--border-hover)", color: "var(--text-2)" }}>Save quote</button>
        <div className="mt-3 t-body-sm font-medium" style={{ color: "var(--text-3)" }}>Batch budget</div>
        {stored.budget.length ? <ul className="m-0 list-none p-0">{stored.budget.map((r) => show(r))}</ul> : <p className="m-0 t-body-sm">No budget saved.</p>}
        <div className="mt-1 flex flex-wrap items-end gap-2">
          <Lbl text="Budget (rupees)"><input aria-label="Budget" inputMode="decimal" className={inputCls} value={budget} onChange={(e) => setBudget(e.target.value)} /></Lbl>
          <button type="button" className={btn} onClick={() => void saveBudget()} style={{ border: "1px solid var(--border-hover)", color: "var(--text-2)" }}>Save budget</button>
        </div>
        {saved && <span role="status" className="t-meta">{saved}</span>}
        {msg && <div role="alert" className="mt-1 t-meta" style={{ color: "var(--negative)" }}>{msg}</div>}
      </div>
      {problem && <div role="alert" className="t-body-sm" style={{ color: "var(--negative)" }}>{problem}</div>}
      <button type="button" disabled={disabled} onClick={run} className={`${btn} self-start`} style={{ background: "var(--accent)", color: "var(--accent-on-fill)", opacity: disabled ? 0.5 : 1 }}>
        Run new product decision
      </button>
    </div>
  );
}
