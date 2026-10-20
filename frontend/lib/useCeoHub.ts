"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import type {
  AgentAvailability, AgentCode, CeoClient, ClarificationReply, ExplicitPeriod, FindingRow, HealthEntry, InvestigationDetail, InvestigationSummary, MemoryItem, SharedFindingsList, NeedRow, TurnEvent, TurnFlow, TurnResponse,
  UiAction,
} from "@/lib/ceo";
import { RECEIVED_BUT_NO_REPLY, describeError, hubStateOf, isAwaitingAnswer, markPendingFailed, mergeFindings, newSubmissionId, serverAlreadyHasSubmission, stageLabel, submissionFingerprint, withPendingMessage, type HubState } from "@/lib/ceoModel";
import { POLL_INTERVAL_MS, startPollingFeed, type FeedFactory } from "@/lib/ceoPolling";

export type AsyncStatus = "idle" | "loading" | "ready" | "error";

export type TurnProgress = {
  phase: "idle" | "processing";
  question: string | null;
  /** ids of findings that arrived (by polling) while the turn was running: they get an "arrived" marker */
  arrivedIds: string[];
  error: string | null;
  last: TurnResponse | null;
  /** plain words for what the turn is doing right now, from the live event stream (null when none has arrived: the poll still works) */
  stage: string | null;
  /** registry keys of the specialist actions running right now (from the live LEG_STARTED / LEG_FINISHED events); drives the agent strip only */
  working: string[];
  /** registry keys the CEO has routed this turn to (from CLASSIFIED / PLAN_VALIDATED / STATE_READ), kept until the turn ends so the agent stays lit while its answer is read and written up */
  called?: string[];
};

export type HealthState = { status: "loading" | "ready" | "error"; entries: HealthEntry[] };
export type FlowState = { status: "loading" | "ready" | "error"; data: TurnFlow | null; error: string | null };

const IDLE_TURN: TurnProgress = { phase: "idle", question: null, arrivedIds: [], error: null, last: null, stage: null, working: [] };

const OPEN_KEY = "metrion.ceoHub.openInvestigation";
/** The open conversation is remembered for this browser tab only, so a refresh does not drop the seller's place. Storage can be unavailable
 * (private window, blocked site data): every access is guarded and the Hub works exactly as before without it. */
const rememberOpen = (id: string | null): void => {
  try {
    if (id) sessionStorage.setItem(OPEN_KEY, id);
    else sessionStorage.removeItem(OPEN_KEY);
  } catch {
    /* no storage: nothing is remembered */
  }
};
const rememberedOpen = (): string | null => {
  try {
    return sessionStorage.getItem(OPEN_KEY);
  } catch {
    return null;
  }
};

/** How often an unanswered question is re-read (the thread only; no findings, no money). */
const AWAIT_POLL_MS = 3000;
/** Another turn of this conversation is still running: the new message was REFUSED (nothing stored), which is not a failure of the running task. */
const isTurnBusy = (e: unknown): boolean => e instanceof ApiError && e.status === 409 && (e.detail as { code?: string } | null)?.code === "TURN_IN_PROGRESS";

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
  const [health, setHealth] = useState<HealthState>({ status: "loading", entries: [] });
  const [flows, setFlows] = useState<Record<string, FlowState>>({});
  const [memory, setMemory] = useState<MemoryItem[]>([]);
  const [shared, setShared] = useState<{ status: "loading" | "ready" | "error"; data: SharedFindingsList | null }>({ status: "loading", data: null });
  const [needs, setNeeds] = useState<NeedRow[]>([]);
  const selectedRef = useRef<string | null>(null);
  const findingsRef = useRef<FindingRow[]>([]);
  const sendingRef = useRef(false);
  const unansweredRef = useRef<{ fingerprint: string; id: string } | null>(null); // the last send that got no answer: sending it again unchanged is a RETRY and keeps its id
  const detailRef = useRef(detail);
  detailRef.current = detail;
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

  /** The CEO's follow-up lookups: a convenience read. If it cannot load, the conversation still shows everything else. */
  const loadNeeds = useCallback(
    async (id: string) => {
      try {
        const { items } = await client.getNeeds(id);
        if (selectedRef.current === id) setNeeds(items);
      } catch {
        if (selectedRef.current === id) setNeeds([]);
      }
    },
    [client],
  );

  const loadDetail = useCallback(
    async (id: string, quiet: boolean) => {
      if (!quiet) setDetail({ status: "loading", data: null, error: null });
      try {
        const data = await client.getInvestigation(id);
        if (selectedRef.current === id) {
          setDetail({ status: "ready", data, error: null });
          void loadNeeds(id);
        }
        return data;
      } catch (e) {
        if (selectedRef.current !== id) return null;
        if (e instanceof ApiError && e.status === 404) setDetail({ status: "notfound", data: null, error: null });
        else setDetail((d) => ({ status: "error", data: quiet ? d.data : null, error: failure(e) }));
        return null;
      }
    },
    [client, loadNeeds],
  );

  const select = useCallback(
    (id: string | null) => {
      selectedRef.current = id;
      rememberOpen(id);
      setSelectedId(id);
      setTurn(IDLE_TURN);
      setNotice(null);
      setFlows({});
      setNeeds([]);
      if (id) void loadDetail(id, false);
      else setDetail({ status: "idle", data: null, error: null });
    },
    [loadDetail],
  );

  // Once the list has loaded, reopen the conversation that was open before a refresh, but only if it is still in the seller's list and
  // nothing else was opened or created in the meantime. A remembered id that is no longer listed is forgotten.
  const restoredRef = useRef(false);
  useEffect(() => {
    if (restoredRef.current || list.status !== "ready") return;
    restoredRef.current = true;
    const remembered = rememberedOpen();
    if (!remembered || selectedRef.current !== null) return;
    if (list.items.some((i) => i.id === remembered)) select(remembered);
    else rememberOpen(null);
  }, [list.status, list.items, select]);

  const refreshMemory = useCallback(async () => {
    try {
      setMemory((await client.getMemory()).items);
    } catch {
      /* memory is a convenience panel: if it cannot load, the Hub works without it */
    }
  }, [client]);

  /** What the agents have reported (a separate, trust-labelled tier from "What I remember"). A failed read keeps what was already shown and says so. */
  const refreshShared = useCallback(async () => {
    try {
      setShared({ status: "ready", data: await client.getSharedFindings() });
    } catch {
      setShared((s) => ({ status: "error", data: s.data }));
    }
  }, [client]);

  const forgetShared = useCallback(
    async (id: string) => {
      try {
        await client.forgetSharedFinding(id);
      } catch {
        /* already gone or not allowed: the refresh below shows the truth */
      }
      await refreshShared();
    },
    [client, refreshShared],
  );

  const forgetMemory = useCallback(
    async (id: string) => {
      try {
        await client.forgetMemory(id);
      } catch {
        /* already gone or not allowed: the refresh below shows the truth */
      }
      await refreshMemory();
    },
    [client, refreshMemory],
  );

  const refreshHealth = useCallback(async () => {
    try {
      const { entries } = await client.getHealth();
      setHealth({ status: "ready", entries });
    } catch {
      setHealth((h) => ({ status: "error", entries: h.entries }));
    }
  }, [client]);

  useEffect(() => {
    void refreshList();
    void refreshHealth();
    void refreshMemory();
    void refreshShared();
    client.getAvailability().then(setAvailability, () => setAvailability(null));
  }, [client, refreshList, refreshHealth, refreshMemory, refreshShared]);

  /** "Show flow": read the audit rows for one turn, once, on demand. */
  const loadFlow = useCallback(
    async (turnId: string) => {
      const id = selectedRef.current;
      if (!id) return;
      setFlows((f) => ({ ...f, [turnId]: { status: "loading", data: null, error: null } }));
      try {
        const data = await client.getFlow(id, turnId);
        setFlows((f) => ({ ...f, [turnId]: { status: "ready", data, error: null } }));
      } catch (e) {
        setFlows((f) => ({ ...f, [turnId]: { status: "error", data: null, error: failure(e) } }));
      }
    },
    [client],
  );

  const create = useCallback(
    async (title?: string) => {
      try {
        const { investigationId } = await client.createInvestigation(title?.trim() || undefined);
        await refreshList();
        select(investigationId);
        return investigationId;
      } catch (e) {
        setNotice(failure(e));
        return null;
      }
    },
    [client, refreshList, select],
  );

  const sendTurn = useCallback(
    async (message: string, period: ExplicitPeriod | null, action: UiAction | null = null, clarification: ClarificationReply | null = null, attachmentIds: string[] = [], ciFindingId: string | null = null) => {
      const id = selectedRef.current;
      if (!id) return;
      const text = message.trim();
      if (!text) return;
      if (sendingRef.current) return; // one submission in flight at a time from this screen (the server refuses an overlapping turn too: 409)
      sendingRef.current = true;
      const fingerprint = submissionFingerprint(id, text, period, action, clarification, attachmentIds);
      const clientRequestId = unansweredRef.current?.fingerprint === fingerprint ? unansweredRef.current.id : newSubmissionId();
      unansweredRef.current = { fingerprint, id: clientRequestId };
      const userBefore = (detailRef.current.data?.messages ?? []).filter((m) => m.role === "USER" && !m.pending && !m.failed).length;
      setNotice(null);
      setTurn({ phase: "processing", question: text, arrivedIds: [], error: null, last: null, stage: null, working: [] });
      setDetail((d) => (d.data ? { ...d, data: { ...d.data, messages: withPendingMessage(d.data.messages, text, new Date().toISOString()) } } : d));

      const known = new Set(findingsRef.current.map((f) => f.id)); // what was already on screen before this turn
      const onFindings = (incoming: FindingRow[]) => {
        if (selectedRef.current !== id) return;
        const fresh = incoming.filter((f) => !known.has(f.id)).map((f) => f.id);
        if (fresh.length === 0) return; // nothing new: no state change, no re-render
        fresh.forEach((fid) => known.add(fid));
        setDetail((d) => (d.data ? { ...d, data: { ...d.data, findings: mergeFindings(d.data.findings, incoming) } } : d));
        setTurn((t) => (t.phase === "processing" ? { ...t, arrivedIds: [...t.arrivedIds, ...fresh] } : t));
      };
      const feed = feedFactory({ intervalMs: pollMs, fetchFindings: () => client.getFindings(id), onFindings });

      // Live progress (SSE). An accelerator only: it shows what the turn is doing and fetches findings the moment a leg finishes, instead of at the
      // next poll. If it cannot open, or never delivers, the poll above is already doing the whole job.
      const events = new AbortController();
      void client
        .streamEvents(
          id,
          (e: TurnEvent) => {
            if (selectedRef.current !== id) return;
            const label = stageLabel(e.kind);
            if (label) setTurn((t) => (t.phase === "processing" ? { ...t, stage: label } : t));
            const action = typeof e.data?.action === "string" ? e.data.action : null;
            const routed = e.kind === "CLASSIFIED" || e.kind === "PLAN_VALIDATED" ? e.data?.routeKey : e.kind === "STATE_READ" ? e.data?.entry : null;
            if (typeof routed === "string" && routed) setTurn((t) => (t.phase === "processing" && !(t.called ?? []).includes(routed) ? { ...t, called: [...(t.called ?? []), routed] } : t));
            if (action && e.kind === "LEG_STARTED") setTurn((t) => (t.phase === "processing" ? { ...t, working: [...t.working, action] } : t));
            if (action && e.kind === "LEG_FINISHED") setTurn((t) => ({ ...t, working: t.working.filter((a) => a !== action) }));
            if (e.kind === "LEG_FINISHED" || e.kind === "STATE_READ") void client.getFindings(id).then(onFindings, () => undefined);
          },
          events.signal,
        )
        .catch(() => undefined);

      let error: string | null = null;
      let last: TurnResponse | null = null;
      try {
        last = await client.postTurn(id, text, period, action, clarification, attachmentIds, clientRequestId, ciFindingId);
        unansweredRef.current = null; // answered: the next send, even with identical text, is a new submission
      } catch (e) {
        if (isTurnBusy(e)) setNotice(failure(e)); // told once as a notice; the running task keeps its own status
        else error = failure(e);
      } finally {
        feed.stop();
        events.abort();
        sendingRef.current = false;
      }
      if (selectedRef.current === id) {
        if (error) setDetail((d) => (d.data ? { ...d, data: { ...d.data, messages: markPendingFailed(d.data.messages) } } : d)); // if the refresh below also fails, the question reads as not sent
        const fresh = await loadDetail(id, true); // the authoritative thread: the server's copy replaces the pending message
        if (error && fresh && serverAlreadyHasSubmission(fresh.messages, text, userBefore)) error = RECEIVED_BUT_NO_REPLY; // a lost reply, not a lost question: do not invite a resend
        setTurn((t) => ({ phase: "idle", question: null, arrivedIds: t.arrivedIds, error, last, stage: null, working: [] }));
      }
      void refreshList();
      void refreshHealth(); // a turn can read or trigger saved results; the strip is a cheap persisted read
      void refreshMemory(); // a turn can remember something the seller stated
      void refreshShared(); // and a specialist that finished can have reported something
    },
    [client, feedFactory, pollMs, loadDetail, refreshList, refreshHealth, refreshMemory, refreshShared],
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

  // The Approve / Decline buttons of a plan card. Approving is an explicit call bound to the plan id AND the plan hash the seller was shown; the server runs exactly the frozen
  // plan once. Nothing typed in the chat reaches this. The thread is re-read afterwards: the result (or the refusal) is a stored message, never composed here.
  const [planBusy, setPlanBusy] = useState<string | null>(null);
  const decidePlan = useCallback(
    async (planId: string, act: () => Promise<unknown>) => {
      const id = selectedRef.current;
      if (!id || planBusy) return;
      setPlanBusy(planId);
      setNotice(null);
      try {
        await act();
      } catch (e) {
        const detail = e instanceof ApiError && e.detail && typeof e.detail === "object" ? (e.detail as { message?: unknown }).message : null;
        setNotice(typeof detail === "string" && detail.trim() ? detail : failure(e));
      } finally {
        setPlanBusy(null);
        await Promise.all([loadDetail(id, true), refreshList()]);
        void refreshHealth();
      }
    },
    [planBusy, loadDetail, refreshList, refreshHealth],
  );
  const approvePlan = useCallback((planId: string, planHash: string) => decidePlan(planId, () => client.approvePlan(selectedRef.current as string, planId, planHash)), [client, decidePlan]);
  const declinePlan = useCallback((planId: string) => decidePlan(planId, () => client.declinePlan(selectedRef.current as string, planId, null)), [client, decidePlan]);

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

  /** "Delete" a conversation from the seller's list. The server keeps conversation history, findings and the audit record permanently (they are never purged), so this hides it
   * (ARCHIVED) and takes it off the screen; it is the same server call as Archive. */
  const removeConversation = useCallback(async (id: string) => {
    try {
      await client.archive(id);
      await refreshList();
      if (selectedRef.current === id) await loadDetail(id, true);
    } catch (e) {
      setNotice(failure(e));
    }
  }, [client, loadDetail, refreshList]);

  // A question the server stored but has not answered (refresh mid-run, lost reply): shown as still being answered and re-read until the answer arrives. The composer stays
  // usable on purpose: a send is how an abandoned turn gets settled and reported, and the server refuses it with a plain notice while a live turn still owns the conversation.
  const awaitingAnswer = turn.phase === "idle" && detail.status === "ready" && isAwaitingAnswer(detail.data?.messages, detail.data?.investigation.status);
  useEffect(() => {
    if (!awaitingAnswer || !selectedId) return;
    const timer = setInterval(() => void loadDetail(selectedId, true), AWAIT_POLL_MS);
    return () => clearInterval(timer);
  }, [awaitingAnswer, selectedId, loadDetail]);

  const state: HubState = hubStateOf({ selectedId, status: detail.status, detail: detail.data, processing: turn.phase === "processing" });

  return {
    awaitingAnswer, state, list, availability, health, memory, needs, forgetMemory, shared, forgetShared, refreshShared, flows, loadFlow, refreshHealth, selectedId, detail, turn, showArchived, setShowArchived, busyAgent, notice, dismissNotice: () => setNotice(null),
    refreshList, select, create, sendTurn, setAttached, resolve, reopen, archive, removeConversation, approvePlan, declinePlan, planBusy, retryDetail: () => selectedRef.current && loadDetail(selectedRef.current, false),
  };
}
