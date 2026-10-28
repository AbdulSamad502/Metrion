"use client";

import { useId, useRef, useState, type ReactNode } from "react";
import { Icon, type IconName } from "@/components/ui/Icon";
import { PNL_FULFILMENT, PNL_MARKETPLACES, activeFeeFields, type PnlFulfilment, type PnlMarketplace } from "@/lib/pnlFeeFields";
import { exampleForm, newFeeEntry, type PnlBand, type PnlFeeEntry, type PnlField, type PnlForm } from "@/lib/pnlScenario";

/** One typed number with an explicit "not applicable" switch. Leaving it blank means "not entered" (the result then says what is missing); it is never
 * read as zero. "Not applicable" is the seller confirming the amount really is zero. */
function NumberField({
  label, hint, value, onChange, error, unit, allowNa = true, placeholder,
}: {
  label: string; hint?: ReactNode; value: PnlField; onChange: (next: PnlField) => void; error?: string; unit: "₹" | "%" | "orders"; allowNa?: boolean; placeholder?: string;
}) {
  const id = useId();
  const entered = !value.na && value.text.trim() !== "" && !error;
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="mb-1.5 block t-body-sm font-medium" style={{ color: "var(--text-4)" }}>{label}</label>
      <div
        className="mt-input flex min-h-10 items-center gap-2 px-3 py-0 focus-within:!border-[var(--accent)] focus-within:shadow-[0_0_0_3px_var(--accent-fill-default)]"
        style={{ opacity: value.na ? 0.6 : 1, borderColor: error ? "var(--negative)" : undefined }}
      >
        {unit === "₹" && <span aria-hidden className="t-body-sm" style={{ color: "var(--text-5)" }}>₹</span>}
        <input
          id={id}
          inputMode="decimal"
          autoComplete="off"
          value={value.na ? "" : value.text}
          disabled={value.na}
          placeholder={value.na ? "Doesn't apply" : (placeholder ?? "Not entered")}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-err` : hint ? `${id}-hint` : undefined}
          onChange={(e) => onChange({ text: e.target.value, na: false })}
          className="min-w-0 flex-1 border-0 bg-transparent py-2 t-body outline-none"
          style={{ color: "var(--text-1)" }}
        />
        {entered && <span aria-hidden className="flex flex-shrink-0" style={{ color: "var(--accent)" }}><Icon name="check" size={16} /></span>}
        {unit === "%" && <span aria-hidden className="flex-shrink-0 border-l pl-3 t-body-sm" style={{ color: "var(--text-5)", borderColor: "var(--border-default)" }}>%</span>}
        {unit === "orders" && <span aria-hidden className="flex-shrink-0 t-body-sm" style={{ color: "var(--text-5)" }}>orders</span>}
      </div>
      {allowNa && (
        <label
          className="mt-chip mt-2 inline-flex min-h-10 cursor-pointer items-center gap-2 rounded-full px-3 t-meta focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-[var(--accent)]"
          style={{ border: `1px solid ${value.na ? "var(--accent-border-strong)" : "var(--border-default)"}`, color: value.na ? "var(--accent)" : "var(--text-4)", background: value.na ? "var(--accent-fill-default)" : "transparent" }}
        >
          <input type="checkbox" className="h-6 w-6 flex-shrink-0 cursor-pointer" style={{ accentColor: "var(--accent)" }} checked={value.na} onChange={(e) => onChange({ text: "", na: e.target.checked })} />
          <span>{unit === "%" ? "Doesn't apply (0%)" : "Doesn't apply (₹0)"}</span>
        </label>
      )}
      {error ? (
        <p id={`${id}-err`} role="alert" className="mt-1.5 t-meta" style={{ color: "var(--negative)" }}>{error}</p>
      ) : hint ? (
        <p id={`${id}-hint`} className="mt-1.5 t-meta" style={{ color: "var(--text-5)" }}>{hint}</p>
      ) : null}
    </div>
  );
}

/** Pill-style single choice. Real radio inputs underneath (arrow keys, labels and screen readers work as for any radio group). */
function PillChoice<T extends string>({ legend, value, options, onChange, segmented = false }: { legend: string; value: T; options: { id: T; label: string }[]; onChange: (v: T) => void; segmented?: boolean }) {
  return (
    <fieldset className="m-0 border-0 p-0">
      <legend className="mb-1.5 p-0 t-body-sm font-medium" style={{ color: "var(--text-4)" }}>{legend}</legend>
      <div className={segmented ? "inline-grid w-fit max-w-full auto-cols-fr grid-flow-col gap-1 rounded-full p-1" : "flex flex-wrap gap-2"} style={segmented ? { border: "1px solid var(--border-default)", background: "var(--fill-hover)" } : undefined}>
        {options.map((o) => {
          const on = value === o.id;
          return (
            <label
              key={o.id}
              className={`mt-chip flex min-h-10 cursor-pointer items-center rounded-full px-3 sm:px-5 t-body-sm font-medium focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-[var(--accent)] ${segmented ? "justify-center text-center" : ""}`}
              style={{ background: on ? "var(--accent-fill-default)" : "transparent", border: `1px solid ${on ? "var(--accent-border-strong)" : "var(--border-default)"}`, color: on ? "var(--accent)" : "var(--text-3)" }}
            >
              <input type="radio" name={legend} className="sr-only" checked={on} onChange={() => onChange(o.id)} />
              {o.label}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

const GST_STATUS: { id: PnlForm["gstStatus"]; title: string; detail: string }[] = [
  { id: "registered_itc", title: "Registered + ITC", detail: "GST is not income; GST you pay is recovered." },
  { id: "registered_no_itc", title: "Registered, no ITC", detail: "GST is not income; GST you pay is a cost." },
  { id: "unregistered", title: "Not registered", detail: "No GST collected; GST you pay is a cost." },
];

/** The three GST situations as cards. The accessible name of each radio is its title; the sentence below is its description. */
function GstStatusCards({ value, onChange }: { value: PnlForm["gstStatus"]; onChange: (v: PnlForm["gstStatus"]) => void }) {
  return (
    <fieldset className="m-0 border-0 p-0">
      <legend className="mb-1.5 p-0 t-body-sm font-medium" style={{ color: "var(--text-5)" }}>GST status</legend>
      <div className="grid gap-2 sm:grid-cols-3">
        {GST_STATUS.map((o) => {
          const on = value === o.id;
          return (
            <label
              key={o.id}
              className="mt-chip flex cursor-pointer flex-col gap-1 rounded-xl p-3 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-[var(--accent)]"
              style={{ background: on ? "var(--accent-fill-default)" : "transparent", border: `1px solid ${on ? "var(--accent-border-strong)" : "var(--border-default)"}` }}
            >
              <input type="radio" name="GST status" className="sr-only" checked={on} onChange={() => onChange(o.id)} aria-describedby={`gst-${o.id}`} />
              <span className="t-body-sm font-semibold" style={{ color: on ? "var(--accent)" : "var(--text-2)" }}>{o.title}</span>
              <span id={`gst-${o.id}`} className="t-meta" style={{ color: "var(--text-5)" }}>{o.detail}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

/** Quick-pick GST rates. They only type the number into the field for you (any rate can still be typed); nothing here decides which rate applies. */
const GST_CHIPS = ["0", "5", "18", "40"] as const;

function Chip({ label, on, onClick }: { label: string; on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className="mt-chip mt-focus min-h-10 rounded-full px-4 t-body-sm font-medium"
      style={{ background: on ? "var(--accent-fill-default)" : "transparent", border: `1px solid ${on ? "var(--accent-border-strong)" : "var(--border-default)"}`, color: on ? "var(--accent)" : "var(--text-3)" }}
    >
      {label}
    </button>
  );
}

function GstRateField({ value, onChange, error }: { value: PnlField; onChange: (next: PnlField) => void; error?: string }) {
  const wrap = useRef<HTMLDivElement>(null);
  const typed = value.na ? "" : value.text.trim();
  const isChip = (GST_CHIPS as readonly string[]).includes(typed);
  const chooseOther = () => {
    onChange({ text: isChip ? "" : value.text, na: false });
    wrap.current?.querySelector<HTMLInputElement>("input[type=text], input:not([type])")?.focus();
  };
  return (
    <div ref={wrap} className="flex flex-col gap-2">
      <NumberField label="Product GST rate" unit="%" value={value} onChange={onChange} error={error} hint="The GST rate on this product. The buttons below just type it for you." />
      <div className="flex flex-wrap gap-2" role="group" aria-label="Common GST rates">
        {GST_CHIPS.map((c) => <Chip key={c} label={`${c}%`} on={typed === c} onClick={() => onChange({ text: c, na: false })} />)}
        <Chip label="Other" on={typed !== "" && !isChip} onClick={chooseOther} />
      </div>
    </div>
  );
}

type StepTone = "info" | "warning" | "rose" | "violet" | "accent";

/** A numbered, collapsible step with a tick once everything in it has been entered. "Entered" only means something was typed or marked not applicable; it
 * does not mean the values are right. The icon and tint only help tell the steps apart; each is named in words. */
function StepCard({ n, title, subtitle, done, open, onToggle, icon, tone, wide = false, children }: { n: number; title: string; subtitle: string; done: boolean; open: boolean; onToggle: () => void; icon: IconName; tone: StepTone; wide?: boolean; children: ReactNode }) {
  const id = useId();
  return (
    <section className={`ov-card pnl-step ${wide ? "lg:col-span-2" : ""}`} data-testid={`step-${n}`}>
      <h2 className="m-0">
        <button type="button" aria-expanded={open} aria-controls={id} onClick={onToggle} className="pnl-step-head mt-focus flex min-h-14 w-full cursor-pointer items-center gap-3 text-left">
          <span aria-hidden className="pnl-step-icon flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl" data-tone={tone}><Icon name={icon} size={20} /></span>
          <span className="min-w-0 flex-1">
            <span className="block t-body font-semibold" style={{ color: "var(--text-1)" }}><span aria-hidden>{n}. </span>{title}</span>
            <span className="block t-meta" style={{ color: "var(--text-5)" }}>{subtitle}</span>
          </span>
          {done && (
            <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full" style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}>
              <Icon name="check" size={14} />
              <span className="sr-only">Entered</span>
            </span>
          )}
          <span aria-hidden style={{ color: "var(--text-5)", transform: open ? "rotate(180deg)" : "none", display: "inline-flex" }}><Icon name="chevron" size={18} /></span>
        </button>
      </h2>
      <div id={id} hidden={!open} className="pnl-step-body">{children}</div>
    </section>
  );
}

const answered = (f: PnlField): boolean => f.na || f.text.trim() !== "";
/** A fee counts as entered when its single amount is answered, or (price bands on) every band has its limit and rate. */
const feeAnswered = (f: PnlFeeEntry): boolean => (f.useTiers ? f.bands.every((b, i) => (i === f.bands.length - 1 || b.upTo.trim() !== "") && b.rate.trim() !== "") : answered(f));

/** Price bands for a fee that changes with the selling price: "up to ₹X" and the rate or amount charged, the last band having no upper limit. The engine checks the
 * bands (order, gaps, overlap) and says what is wrong; this editor only collects what was typed. */
function BandEditor({ def, entry, errors, onChange }: { def: { id: string; label: string; unit: "percent" | "flat"; help: string }; entry: PnlFeeEntry; errors: Record<string, string>; onChange: (patch: Partial<PnlFeeEntry>) => void }) {
  const percent = def.unit === "percent";
  const setBand = (i: number, patch: Partial<PnlBand>) => onChange({ bands: entry.bands.map((b, j) => (j === i ? { ...b, ...patch } : b)) });
  return (
    <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
      <legend className="p-0 t-body-sm font-semibold" style={{ color: "var(--text-2)" }}>{def.label} by price band</legend>
      <p className="m-0 t-meta" style={{ color: "var(--text-6)" }}>{def.help}</p>
      <div>
        <label htmlFor={`mode-${def.id}`} className="mb-1.5 block t-body-sm font-medium" style={{ color: "var(--text-5)" }}>Band type</label>
        <select id={`mode-${def.id}`} value={entry.tierMode} onChange={(e) => onChange({ tierMode: e.target.value === "marginal" ? "marginal" : "whole" })} className="mt-input rounded-lg px-3 py-2 t-body">
          <option value="whole">The rate applies to the whole price</option>
          {percent && <option value="marginal">Progressive (each slice has its own rate)</option>}
        </select>
      </div>
      {entry.bands.map((b, i) => {
        const last = i === entry.bands.length - 1;
        return (
          <div key={i} className="grid gap-3 sm:grid-cols-2">
            {last ? (
              <p className="m-0 flex min-h-10 items-center t-body-sm" style={{ color: "var(--text-5)" }}>Above the last limit</p>
            ) : (
              <NumberField label={`Band ${i + 1}: up to`} unit="₹" value={{ text: b.upTo, na: false }} onChange={(n) => setBand(i, { upTo: n.text })} error={errors[`fee.${def.id}.band.${i}.upTo`]} allowNa={false} />
            )}
            <NumberField label={`Band ${i + 1}: ${percent ? "rate" : "amount"}`} unit={percent ? "%" : "₹"} value={{ text: b.rate, na: false }} onChange={(n) => setBand(i, { rate: n.text })} error={errors[`fee.${def.id}.band.${i}.rate`]} allowNa={false} />
          </div>
        );
      })}
      <div className="flex gap-3 t-body-sm">
        <button type="button" className="mt-focus min-h-10 font-semibold underline" style={{ color: "var(--accent)" }} onClick={() => onChange({ bands: [{ upTo: "", rate: "" }, ...entry.bands] })}>Add band</button>
        {entry.bands.length > 2 && <button type="button" className="mt-focus min-h-10 underline" style={{ color: "var(--text-5)" }} onClick={() => onChange({ bands: entry.bands.slice(1) })}>Remove first band</button>}
      </div>
    </fieldset>
  );
}

export function PnlInputs({ form, setForm, errors, onReset, onExample }: { form: PnlForm; setForm: (update: (f: PnlForm) => PnlForm) => void; errors: Record<string, string>; onReset: () => void; onExample: () => void }) {
  const set = <K extends keyof PnlForm>(key: K, value: PnlForm[K]) => setForm((f) => ({ ...f, [key]: value }));
  const field = (key: keyof PnlForm) => (next: PnlField) => set(key, next as never);
  const registered = form.gstStatus !== "unregistered";
  const detailed = form.mode === "detailed";
  const fees = activeFeeFields(form.marketplace, form.fulfilment, form.mode);
  const setFee = (id: string, patch: Partial<PnlFeeEntry>) =>
    setForm((f) => ({ ...f, fees: { ...f.fees, [id]: { ...(f.fees[id] ?? newFeeEntry()), ...patch } } }));
  const setRecovery = (which: "rtoRecovery" | "returnRecovery", part: "sellable" | "damaged", next: PnlField) =>
    setForm((f) => ({ ...f, [which]: { ...f[which], [part]: next } }));

  const [openSteps, setOpenSteps] = useState<Record<number, boolean>>({ 1: true, 2: true, 3: true, 4: true, 5: true });
  const toggle = (n: number) => setOpenSteps((o) => ({ ...o, [n]: !o[n] }));

  // Which steps are fully entered. A tick means "something was entered or marked not applicable for every field here", never that the values are valid.
  const steps = [
    { n: 1, name: "Product", done: answered(form.sellingPrice) && answered(form.productCost) && (!registered || answered(form.gstRate)) && (!detailed || answered(form.packaging)) },
    // The key fees (the ones Quick mode asks for). Optional extras such as a return handling fee do not hold the tick back; if one matters the result names it as missing.
    { n: 2, name: "Fees", done: fees.filter((d) => d.quick).every((d) => feeAnswered(form.fees[d.id] ?? newFeeEntry())) },
    { n: 3, name: "Orders", done: answered(form.monthlyOrders) && answered(form.rto) && answered(form.returns) },
    ...(detailed ? [{ n: 4, name: "Advertising", done: answered(form.adSpend) }] : []),
  ];
  const doneCount = steps.filter((s) => s.done).length;

  return (
    <div className="flex flex-col gap-5">
      <div className="ov-card grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-3">
          <PillChoice legend="Marketplace" segmented value={form.marketplace} options={PNL_MARKETPLACES} onChange={(v: PnlMarketplace) => setForm((f) => (f.isExample ? exampleForm(v, f.mode) : { ...f, marketplace: v, fees: {}, fulfilment: "easy_ship" }))} />
          <PillChoice legend="Detail" segmented value={form.mode} options={[{ id: "quick", label: "Expected" }, { id: "detailed", label: "Detailed" }]} onChange={(v) => set("mode", v)} />
          <p className="t-meta" style={{ color: "var(--text-6)" }}>{detailed ? "Detailed: adds packaging, advertising, operating costs, return/RTO handling fees, fee refunds, price bands and damaged stock." : "Expected: only the key numbers (price, cost, fees, returns). A quick profit and loss. It leaves out packaging, advertising, operating costs and return/RTO handling fees."}</p>
        </div>
        <div className="flex flex-col gap-2.5" data-testid="progress">
          <p className="m-0 t-body-sm font-semibold" style={{ color: doneCount === steps.length ? "var(--accent)" : "var(--text-2)" }} aria-live="polite">
            {doneCount === steps.length ? "All set: choose Calculate to see your result." : `${doneCount} of ${steps.length} steps entered`}
          </p>
          <div role="progressbar" aria-label="Steps entered" aria-valuemin={0} aria-valuemax={steps.length} aria-valuenow={doneCount} className="h-2 overflow-hidden rounded-full" style={{ background: "var(--fill-hover)" }}>
            <div className="h-full rounded-full" style={{ width: `${(doneCount / steps.length) * 100}%`, background: "var(--accent)" }} />
          </div>
          <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
            {steps.map((s) => (
              <li key={s.n} className="flex items-center gap-1 rounded-full px-2.5 py-1 t-meta" style={{ border: `1px solid ${s.done ? "var(--accent-border-default)" : "var(--border-default)"}`, color: s.done ? "var(--accent)" : "var(--text-5)" }}>
                {s.done && <Icon name="check" size={14} />}
                <span>{s.name}</span>
                <span className="sr-only">{s.done ? " entered" : " not finished"}</span>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-3">
            <button type="button" onClick={onExample} className="mt-btn mt-focus min-h-10 rounded-lg px-3 t-body-sm font-semibold" style={{ border: "1px solid var(--accent-border-strong)", color: "var(--accent)" }}>Try with example numbers</button>
            <button type="button" onClick={onReset} className="mt-btn mt-focus min-h-10 rounded-lg px-3 t-body-sm font-semibold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}>Reset</button>
            <span className="t-meta" style={{ color: "var(--text-6)" }}>Not saved. Sent to Metrion only to work out the estimate.</span>
          </div>
          {form.isExample && (
            <p role="note" className="m-0 rounded-lg px-3 py-2 t-body-sm" style={{ background: "var(--warning-fill)", border: "1px solid var(--warning-border)", color: "var(--warning)" }} data-testid="example-note">
              <strong>Example data — not real marketplace rates.</strong> These numbers are made up to show how the calculator works. Replace them with your own, or choose Reset.
            </p>
          )}
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2 lg:items-start">
      <StepCard n={1} icon="tag" tone="info" title="Product and price" subtitle="What you sell it for and what it costs you" done={steps[0].done} open={openSteps[1]} onToggle={() => toggle(1)}>
        <div className="grid gap-4 sm:grid-cols-2">
          <NumberField label="Selling price per unit" unit="₹" value={form.sellingPrice} onChange={field("sellingPrice")} error={errors.sellingPrice} allowNa={false} hint="What the customer pays, including GST. Enter it after any seller discount." />
          <NumberField label="Product cost per unit" unit="₹" value={form.productCost} onChange={field("productCost")} error={errors.productCost} hint="What you pay for one unit, as paid including GST." />
          <div className="sm:col-span-2"><GstStatusCards value={form.gstStatus} onChange={(v) => set("gstStatus", v)} /></div>
          {registered && <GstRateField value={form.gstRate} onChange={field("gstRate")} error={errors.gstRate} />}
          {registered && form.gstStatus === "registered_itc" && (
            <NumberField label="GST rate paid on purchase" unit="%" value={form.purchaseGstRate} onChange={field("purchaseGstRate")} error={errors.purchaseGstRate} hint="Leave blank to assume it equals the product rate (stated in the result)." />
          )}
          <NumberField label="GST on marketplace charges, packaging and ads" unit="%" value={form.servicesGstRate} onChange={field("servicesGstRate")} error={errors.servicesGstRate} hint="Leave blank to assume 18% (stated in the result)." />
          {detailed && <NumberField label="Packaging per order" unit="₹" value={form.packaging} onChange={field("packaging")} error={errors.packaging} />}
          {form.marketplace === "amazon" && (
            <div className="sm:col-span-2"><PillChoice legend="Amazon fulfilment" value={form.fulfilment} options={PNL_FULFILMENT} onChange={(v: PnlFulfilment) => set("fulfilment", v)} /></div>
          )}
        </div>
      </StepCard>

      <StepCard n={2} icon="store" tone="warning" title={`${PNL_MARKETPLACES.find((m) => m.id === form.marketplace)?.label ?? ""} fees`} subtitle="From your seller dashboard or settlement report, excluding GST. We never assume a rate." done={steps[1].done} open={openSteps[2]} onToggle={() => toggle(2)}>
        <p className="mb-3 t-meta" style={{ color: "var(--text-6)" }}>Metrion does not fill any fee in. A fee left blank is shown as missing and left out of the profit.</p>
        <div className="grid gap-4">
          {fees.map((def) => {
            const entry = form.fees[def.id] ?? newFeeEntry();
            const hasRefund = detailed && def.chargedOn !== "kept";
            const tiers = detailed && def.tierable;
            const percent = def.unit === "percent";
            return (
              <div key={def.id} className="flex flex-col gap-3 rounded-xl p-3.5" style={{ border: "1px solid var(--border-subtle)", background: "var(--fill-hover)" }} data-testid={`fee-${def.id}`}>
                {entry.useTiers && tiers ? (
                  <BandEditor def={def} entry={entry} errors={errors} onChange={(patch) => setFee(def.id, patch)} />
                ) : (
                  <NumberField label={def.label} unit={percent ? "%" : "₹"} value={entry} onChange={(next) => setFee(def.id, next)} error={errors[`fee.${def.id}`]} hint={def.help} />
                )}
                {tiers && (
                  <label className="flex w-fit cursor-pointer items-center gap-2 t-body-sm" style={{ color: "var(--text-4)" }}>
                    <input type="checkbox" className="mt-focus h-6 w-6 flex-shrink-0 cursor-pointer" style={{ accentColor: "var(--accent)" }} checked={entry.useTiers} onChange={(e) => setFee(def.id, { useTiers: e.target.checked })} />
                    This fee changes with the selling price
                  </label>
                )}
                {(hasRefund || (detailed && percent)) && (
                  <div className="grid gap-4 sm:grid-cols-2">
                    {hasRefund && (
                      <NumberField label={`${def.label}: share refunded on returns`} unit="%" value={entry.refund} onChange={(next) => setFee(def.id, { refund: next })} error={errors[`fee.${def.id}.refund`]} allowNa={false} hint="Optional. Blank means your fees are assumed not refunded (stated in the result)." />
                    )}
                    {detailed && percent && (
                      <div>
                        <label htmlFor={`basis-${def.id}`} className="mb-1.5 block t-body-sm font-medium" style={{ color: "var(--text-5)" }}>{def.label}: charged on</label>
                        <select id={`basis-${def.id}`} value={entry.basis} onChange={(e) => setFee(def.id, { basis: e.target.value as PnlFeeEntry["basis"] })} className="mt-input w-full rounded-lg px-3 py-2 t-body">
                          <option value="">Selling price including GST (default)</option>
                          <option value="price_excl_gst">Selling price excluding GST</option>
                        </select>
                        <p className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>Check your fee report. Blank assumes the price including GST (stated in the result).</p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </StepCard>

      <StepCard n={3} wide icon="returns" tone="rose" title="Orders and returns" subtitle="How many orders come back, and what you recover" done={steps[2].done} open={openSteps[3]} onToggle={() => toggle(3)}>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <NumberField label="Orders placed per month" unit="orders" value={form.monthlyOrders} onChange={field("monthlyOrders")} error={errors.monthlyOrders} hint="Needed for monthly totals, advertising and operating costs." />
          <NumberField label="RTO rate" unit="%" value={form.rto} onChange={field("rto")} error={errors.rto} hint="Orders that never reach the customer." />
          <NumberField label="Customer return rate" unit="%" value={form.returns} onChange={field("returns")} error={errors.returns} hint="Delivered orders sent back." />
        </div>
        {detailed && (
          <details className="mt-4">
            <summary className="mt-focus cursor-pointer t-body-sm font-medium" style={{ color: "var(--text-4)" }}>What happens to returned and RTO stock</summary>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <NumberField label="RTO units resold" unit="%" value={form.rtoRecovery.sellable} onChange={(n) => setRecovery("rtoRecovery", "sellable", n)} error={errors.rtoSellable} hint="Blank assumes 80% (stated in the result)." />
              <NumberField label="RTO units damaged" unit="%" value={form.rtoRecovery.damaged} onChange={(n) => setRecovery("rtoRecovery", "damaged", n)} error={errors.rtoDamaged} allowNa={false} />
              <NumberField label="Returned units resold" unit="%" value={form.returnRecovery.sellable} onChange={(n) => setRecovery("returnRecovery", "sellable", n)} error={errors.returnSellable} hint="Blank assumes 80% (stated in the result)." />
              <NumberField label="Returned units damaged" unit="%" value={form.returnRecovery.damaged} onChange={(n) => setRecovery("returnRecovery", "damaged", n)} error={errors.returnDamaged} allowNa={false} />
              <NumberField label="Resale value of a damaged unit" unit="%" value={form.salvage} onChange={field("salvage")} error={errors.salvage} allowNa={false} hint="As a share of its cost. Blank means none." />
            </div>
          </details>
        )}
      </StepCard>

      {detailed && (
        <StepCard n={4} wide icon="marketing" tone="violet" title="Advertising and overheads" subtitle="Monthly. Operating expenses only add an operating-profit line" done={steps[3].done} open={openSteps[4]} onToggle={() => toggle(4)}>
          <div className="grid gap-4 sm:grid-cols-2">
            <NumberField label="Advertising spend per month" unit="₹" value={form.adSpend} onChange={field("adSpend")} error={errors.adSpend} />
            <NumberField label="Sales attributed to ads per month" unit="₹" value={form.adRevenue} onChange={field("adRevenue")} error={errors.adRevenue} allowNa={false} hint="Optional. Adds ACOS and ROAS." />
            <NumberField label="Operating expenses per month" unit="₹" value={form.operatingExpenses} onChange={field("operatingExpenses")} error={errors.operatingExpenses} hint="Salaries, rent and similar. Do not repeat costs already in your fees." />
          </div>
        </StepCard>
      )}

      <StepCard n={detailed ? 5 : 4} wide icon="target" tone="accent" title="Price targets" subtitle="Assumes your order volume does not change with price" done={false} open={openSteps[5]} onToggle={() => toggle(5)}>
        <div className="grid items-start gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <label className="flex min-h-10 cursor-pointer items-center gap-2 t-body-sm" style={{ color: "var(--text-3)" }}>
            <input type="checkbox" className="mt-focus h-6 w-6 flex-shrink-0 cursor-pointer" style={{ accentColor: "var(--accent)" }} checked={form.wantBreakeven} onChange={(e) => set("wantBreakeven", e.target.checked)} />
            Find my break-even price
          </label>
          <NumberField label="Find the price for a target margin" unit="%" value={form.targetMargin} onChange={field("targetMargin")} error={errors.targetMargin} allowNa={false} hint="Margin on revenue. Blank skips it." />
          <PillChoice legend="Margin type" value={form.targetBasis} options={[{ id: "contribution", label: "Contribution" }, { id: "operating", label: "Operating" }]} onChange={(v) => set("targetBasis", v)} />
        </div>
      </StepCard>
      </div>
    </div>
  );
}
