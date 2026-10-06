"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { EMPTY_INTAKE, newRequestKey, type Marketplace, type ProductIntake, type TitleSetArtefact } from "@/lib/cmo";

/** State shared across the CMO tabs for one working session: the product being worked on, the marketplaces chosen, the title sets
 * generated, the seller's approvals and a ledger of what each call cost. It lives in memory only — the server is the record. */

export type Approval = { approvalId: string; generationId: string; approvedText: string; editedBySeller: boolean };
export type LedgerEntry = { at: string; action: string; units: number; sharedUnits?: number };

type Session = {
  intake: ProductIntake;
  setIntake: (patch: Partial<ProductIntake>) => void;
  marketplaces: Marketplace[];
  setMarketplaces: (m: Marketplace[]) => void;
  titleSets: Partial<Record<Marketplace, TitleSetArtefact>>;
  setTitleSets: (sets: TitleSetArtefact[]) => void;
  approvals: Partial<Record<Marketplace, Approval>>;
  setApproval: (m: Marketplace, a: Approval) => void;
  ledger: LedgerEntry[];
  record: (action: string, units: number, sharedUnits?: number) => void;
  /** A request key is stable for one logical attempt (so a double click or a retry is a replay) and renewed on purpose. */
  keyFor: (slot: string) => string;
  renewKey: (slot: string) => void;
};

const Ctx = createContext<Session | null>(null);

export function CmoSessionProvider({ children }: { children: ReactNode }) {
  const [intake, setIntakeState] = useState<ProductIntake>(EMPTY_INTAKE);
  const [marketplaces, setMarketplaces] = useState<Marketplace[]>([]);
  const [titleSets, setTitleSetsState] = useState<Partial<Record<Marketplace, TitleSetArtefact>>>({});
  const [approvals, setApprovals] = useState<Partial<Record<Marketplace, Approval>>>({});
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const keys = useRef<Record<string, string>>({}); // a ref: reading a key must be stable across renders, never regenerated

  const setIntake = useCallback((patch: Partial<ProductIntake>) => {
    setIntakeState((cur) => ({ ...cur, ...patch }));
    keys.current = {}; // changed inputs are a new request: never replay an old key against different data
  }, []);
  const setTitleSets = useCallback((sets: TitleSetArtefact[]) => {
    setTitleSetsState((cur) => {
      const next = { ...cur };
      for (const s of sets) if (s.marketplace) next[s.marketplace] = s;
      return next;
    });
  }, []);
  const setApproval = useCallback((m: Marketplace, a: Approval) => setApprovals((cur) => ({ ...cur, [m]: a })), []);
  const record = useCallback((action: string, units: number, sharedUnits?: number) => setLedger((cur) => [{ at: new Date().toISOString(), action, units, sharedUnits }, ...cur].slice(0, 200)), []);
  const keyFor = useCallback((slot: string) => (keys.current[slot] ??= newRequestKey(slot)), []);
  const renewKey = useCallback((slot: string) => {
    keys.current[slot] = newRequestKey(slot);
  }, []);

  const value = useMemo<Session>(
    () => ({ intake, setIntake, marketplaces, setMarketplaces, titleSets, setTitleSets, approvals, setApproval, ledger, record, keyFor, renewKey }),
    [intake, setIntake, marketplaces, titleSets, setTitleSets, approvals, setApproval, ledger, record, keyFor, renewKey],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCmoSession(): Session {
  const s = useContext(Ctx);
  if (!s) throw new Error("useCmoSession must be used inside CmoSessionProvider");
  return s;
}
