import type { AgentStatus } from "@/lib/api";
import type { BusinessProfileResponse } from "@/lib/businessProfile";
import type { DemoRoute } from "../respond";
import { isoDaysAgo } from "./dates";

/** SAMPLE replies for the agent roster and the business profile (Sample-data preview). `/ceo-hub/agents` is the backend's own fixed roster
 * (backend/src/backend/api/v1/ceo_hub.py): the same four agents, the same statuses. */
const AGENTS: AgentStatus[] = [
  { id: "CI", name: "Competitor Intelligence", status: "CONNECTED" },
  { id: "PI", name: "Product Intelligence", status: "NOT_CONNECTED" },
  { id: "CFO", name: "CFO", status: "NOT_CONNECTED" },
  { id: "CMO", name: "CMO", status: "CONNECTED" },
];

const profile = (): BusinessProfileResponse => ({
  profile: {
    businessName: "Sample Home Goods",
    description: "We sell stainless-steel kitchen storage and lunch boxes to families across India.",
    categories: "Kitchen storage, lunch boxes",
    marketplaces: ["AMAZON", "FLIPKART", "MEESHO"],
    priceSegment: "MID_RANGE",
    targetCustomer: "Urban families who cook at home",
    businessStage: "GROWING",
    state: "Maharashtra",
    updatedAt: isoDaysAgo(20, 9),
  },
  complete: true,
  suggestedName: null,
});

export const miscRoutes: DemoRoute[] = [
  { method: "GET", match: /^\/api\/v1\/ceo-hub\/agents(\?|$)/, reply: () => AGENTS },
  { method: "GET", match: /^\/api\/v1\/business-profile(\?|$)/, reply: () => profile() },
];
