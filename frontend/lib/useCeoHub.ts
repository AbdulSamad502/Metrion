"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import type {
  AgentAvailability, AgentCode, CeoClient, ExplicitPeriod, FindingRow, InvestigationDetail, InvestigationSummary, TurnResponse,
} from "@/lib/ceo";
import { describeError, hubStateOf, mergeFindings, withPendingMessage, type HubState } from "@/lib/ceoModel";
import { POLL_INTERVAL_MS, startPollingFeed, type FeedFactory } from "@/lib/ceoPolling";

export type AsyncStatus = "idle" | "loading" | "ready" | "error";

export type TurnProgress = {
  phase: "idle" | "processing";
  question: string | null;
  /** ids of findings that arrived (by polling) while the turn was running: they get an "arrived" marker */
  arrivedIds: string[];
  error: string | null;
  last: TurnResponse | null;
};

const IDLE_TURN: TurnProgress = { phase: "idle", question: null, arrivedIds: [], error: null, last: null };

const failure = (e: unknown): string => (e instanceof ApiError ? describeError(e.status, e.detail) : describeError(null, null));

/** All CEO Hub state and actions. The backend decides everything (classification, execution, synthesis, safety); this hook only
 * calls the endpoints, keeps the screen in step with them and polls findings while a turn is running.
 *
 * Fetch discipline: the list and availability load once; an investigation loads on selection and is re-read ONCE after something
 * changes it (a turn, a resolve/archive, an attach/detach). Nothing polls while idle, and polling covers findings only. */
export function useCeoHub(client: CeoClient, feedFactory: FeedFactory = startPollingFeed, pollMs: number = POLL_INTERVAL_MS) {
  const [list, setList] = useState<{ status: AsyncStatus; items: InvestigationSummary[]; error: string | null }>({ status: "loading", items: [], error: null });
  const [availability, setAvailability] = useState<AgentAvailability | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ status: "idle" | "loading" | "ready" | "error" | "notfound"; data: InvestigationDetail | null; error: string | null }>({
    status: "idle", data: null, error: null,
  });
  const [turn, setTurn] = useState<TurnProgress>(IDLE_TURN);
  const [showArchived, setShowArchived] = useState(false);
  const [busyAgent, setBusyAgent] = useState<AgentCode | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const selectedRef = useRef<string | null>(null);
  const findingsRef = useRef<FindingRow[]>([]);
  useEffect(() => {
    findingsRef.current = detail.data?.findings ?? [];
  }, [detail.data]);

  const refreshList = useCallback(async () => {
    try {
      const items = await client.listInvestigations();
      setList({ status: "ready", items, error: null });
    } catch (e) {
      setList((l) => ({ ...l, status: "error", error: failure(e) }));
    }
  }, [client]);

  const loadDetail = useCallback(
    async (id: string, quiet: boolean) => {
      if (!quiet) setDetail({ status: "loading", data: null, error: null });
      try {
        const data = await client.getInvestigation(id);
        if (selectedRef.current === id) setDetail({ status: "ready", data, error: null });
      } catch (e) {
        if (selectedRef.current !== id) return;
        if (e instanceof ApiError && e.status === 404) setDetail({ status: "notfound", data: null, error: null });
        else setDetail((d) => ({ status: "error", data: quiet ? d.data : null, error: failure(e) }));
      }
    },
    [client],
  );

  const select = useCallback(
    (id: string | null) => {
      selectedRef.current = id;
      setSelectedId(id);
      setTurn(IDLE_TURN);
      setNotice(null);
      if (id) void loadDetail(id, false);
      else setDetail({ status: "idle", data: null, error: null });
    },
    [loadDetail],
  );

  useEffect(() => {
    void refreshList();
    client.getAvailability().then(setAvailability, () => setAvailability(null));
  }, [client, refreshList]);

  const create = useCallback(
    async (title?: string) => {
      try {
        const { investigationId } = await client.createInvestigation(title?.trim() || undefined);
        await refreshList();
        select(investigationId);
      } catch (e) {
        setNotice(failure(e));
      }
    },
    [client, refreshList, select],
  );

  const sendTurn = useCallback(
    async (message: string, period: ExplicitPeriod | null) => {
      const id = selectedRef.current;
      if (!id) return;
      const text = message.trim();
      if (!text) return;
      setNotice(null);
      setTurn({ phase: "processing", question: text, arrivedIds: [], error: null, last: null });
      setDetail((d) => (d.data ? { ...d, data: { ...d.data, messages: withPendingMessage(d.data.messages, text, new Date().toISOString()) } } : d));

      const known = new Set(findingsRef.current.map((f) => f.id)); // what was already on screen before this turn
      const feed = feedFactory({
        intervalMs: pollMs,
        fetchFindings: () => client.getFindings(id),
        onFindings: (incoming: FindingRow[]) => {
          if (selectedRef.current !== id) return;
          const fresh = incoming.filter((f) => !known.has(f.id)).map((f) => f.id);
          if (fresh.length === 0) return; // nothing new: no state change, no re-render
          fresh.forEach((fid) => known.add(fid));
          setDetail((d) => (d.data ? { ...d, data: { ...d.data, findings: mergeFindings(d.data.findings, incoming) } } : d));
          setTurn((t) => (t.phase === "processing" ? { ...t, arrivedIds: [...t.arrivedIds, ...fresh] } : t));
        },
      });

      let error: string | null = null;
      let last: TurnResponse | null = null;
      try {
        last = await client.postTurn(id, text, period);
      } catch (e) {
        error = failure(e);
      } finally {
        feed.stop();
      }
      if (selectedRef.current === id) {
        await loadDetail(id, true); // the authoritative thread: the server's copy replaces the pending message
        setTurn((t) => ({ phase: "idle", question: null, arrivedIds: t.arrivedIds, error, last }));
      }
      void refreshList();
    },
    [client, feedFactory, pollMs, loadDetail, refreshList],
  );

  const setAttached = useCallback(
    async (code: AgentCode, attached: boolean) => {
      const id = selectedRef.current;
      if (!id) return;
      setBusyAgent(code);
      setNotice(null);
      try {
        await client.setAgentAttached(id, code, attached);
        await loadDetail(id, true); // re-read once: the agents map and the SYSTEM_NOTE the server wrote
      } catch (e) {
        setNotice(failure(e));
      } finally {
        setBusyAgent(null);
      }
    },
    [client, loadDetail],
  );

  const resolve = useCallback(
    async (note: string) => {
      const id = selectedRef.current;
      if (!id) return;
      try {
        await client.resolve(id, note);
        await Promise.all([loadDetail(id, true), refreshList()]);
      } catch (e) {
        setNotice(failure(e));
      }
    },
    [client, loadDetail, refreshList],
  );

  const reopen = useCallback(async () => {
    const id = selectedRef.current;
    if (!id) return;
    try {
      await client.reopen(id);
      await Promise.all([loadDetail(id, true), refreshList()]);
    } catch (e) {
      setNotice(failure(e));
    }
  }, [client, loadDetail, refreshList]);

  const archive = useCallback(async () => {
    const id = selectedRef.current;
    if (!id) return;
    try {
      await client.archive(id);
      await Promise.all([loadDetail(id, true), refreshList()]);
    } catch (e) {
      setNotice(failure(e));
    }
  }, [client, loadDetail, refreshList]);

  const state: HubState = hubStateOf({ selectedId, status: detail.status, detail: detail.data, processing: turn.phase === "processing" });

  return {
    state, list, availability, selectedId, detail, turn, showArchived, setShowArchived, busyAgent, notice, dismissNotice: () => setNotice(null),
    refreshList, select, create, sendTurn, setAttached, resolve, reopen, archive, retryDetail: () => selectedRef.current && loadDetail(selectedRef.current, false),
  };
}
