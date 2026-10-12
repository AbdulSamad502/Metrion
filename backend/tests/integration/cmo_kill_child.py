"""Child process for the R5 CMO test (not a test module): runs a real billable CMO request and is hard-killed by its own model provider on the first model call
(`os._exit`: no `finally`, no rollback, no terminal write)."""

from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from slim_cmo.service.approve import ApprovalService  # noqa: E402
from slim_cmo.service.catalog import CatalogService  # noqa: E402
from slim_cmo.service.generate import GenerationService, Intake  # noqa: E402
from slim_cmo.repositories.postgres_store import PostgresGenerationStore  # noqa: E402
from slim_cmo.types import ConstraintRowKind as K  # noqa: E402
from slim_cmo import billing  # noqa: E402
from slim_cmo.types import Marketplace, OutputType  # noqa: E402

from backend.repositories import run_liveness  # noqa: E402
from backend.services import cmo_actions, cmo_runtime  # noqa: E402
from backend.services.cmo_runtime import CmoRuntime  # noqa: E402

run_liveness.install_package_ownership()
tenant, user = (uuid.UUID(x) for x in sys.argv[1:3])


class DyingProvider:
    def complete(self, *, model: str, prompt: str) -> str:
        sys.stdout.write("IN_FLIGHT\n")
        sys.stdout.flush()
        os._exit(137)


store = PostgresGenerationStore()
kinds = frozenset({K.TEST_FIXTURE})
clock = cmo_runtime.utc_now
rt = CmoRuntime(store=store, generation=GenerationService(store, DyingProvider(), model="test-model", clock=clock, accepted_row_kinds=kinds),
                approvals=ApprovalService(store, clock=clock, accepted_row_kinds=kinds), catalog=CatalogService(store), clock=clock)
principal = cmo_actions.Principal(tenant, user)
from slim_cmo.service.generate import Actor  # noqa: E402

cmo_actions.run_billable(
    principal, rt, action=billing.Action.GENERATE_TITLE_SETS, items=[billing.RequestedArtefact(OutputType.TITLE_SET, Marketplace.AMAZON)], request_key="kill-me-1",
    execute=lambda run_id: rt.generation.generate_title_sets(
        Actor(tenant, user),
        Intake(request_key="kill-me-1", sku="SKU1", product_name=None, brand="AquaKeep", category_hint=None, attributes=(), notes=(), target_price_paise=None,
               image_analysis_id=None, text_only_confirmed=False, agent_run_id=run_id),
        [Marketplace.AMAZON],
    ),
)
sys.stdout.write("CHILD: returned normally (unexpected)\n")
