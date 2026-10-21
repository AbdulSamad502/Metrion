"""Local-model column-mapping proposer (cfo-data-intelligence.md §6.4, I2, I3, D7).

Asks a LOCAL model (through the existing `LlmProvider` abstraction — text in, text out, no numeric parameter) to
*propose* how an unfamiliar file's columns map onto Metrion's closed vocabulary. The model is shown only column
names, measured shapes and a masked sample of at most a few rows; it never receives a full file, a tenant id, or an
unmasked personal value. What it returns is parsed strictly and then validated deterministically — a proposal is
never trusted, never applied without the seller's confirmation, and an unusable answer becomes
`MappingProposalFailed` (the seller is asked to map manually), never a guess.
"""

from __future__ import annotations

import json
from typing import Any

from data_foundation.mapping import vocab as V
from data_foundation.mapping.masking import is_pii_column, mask_cell
from data_foundation.mapping.service import MappingProposalFailed, ProposerInput

from cfo.reasoning.provider import LlmProvider


def _vocabulary_for(kind: str) -> str:
    lines = []
    for name, spec in V.CANONICAL_FIELDS.items():
        if kind in spec.kinds:
            lines.append(f"- {name} ({spec.value_type})")
    comps = ", ".join(sorted(V.COMPONENT_CODES))
    return "\n".join(lines) + f"\n\ncomponent_amount columns also need component_code, one of: {comps}"


def build_prompt(inp: ProposerInput) -> str:
    cols = []
    for p in inp.profiles:
        cols.append(
            f"[{p.index}] {p.name!r}: non_null={p.non_null}, distinct={p.distinct_count}, numeric_rate={float_free(p.numeric_parse_rate)}, "
            f"negative_share={float_free(p.negative_share)}, max_decimals={p.max_decimal_places}"
            + (f", values={[mask_cell(p.name, v) for v in p.enum_values]}" if p.enum_values and not is_pii_column(p.name) else "")
        )
    sample = "\n".join(" | ".join(r) for r in inp.masked_sample)
    return f"""You map the columns of a seller's {inp.report_kind} report onto a FIXED vocabulary. You do not compute anything.

Allowed canonical fields (use ONLY these names, or leave a column unmapped):
{_vocabulary_for(inp.report_kind)}

Allowed transforms: {sorted(V.TRANSFORMS)} (money columns use RUPEES_TO_PAISE or PAISE_IDENTITY; dates use DATE_ISO, DATE_DMY or DATE_MDY;
percentages use PERCENT; everything else IDENTITY). tax_inclusion is INCLUSIVE, EXCLUSIVE or UNKNOWN. sign_convention is AS_IS or NEGATE.

Rules: never invent a field or a component code; if unsure, put the column in unmapped_columns; do not guess tax inclusion (use UNKNOWN);
reply with ONE JSON object and nothing else, shaped exactly like:
{{"fields":[{{"source_column":"<header>","index":<column position>,"canonical_field":"<name>","component_code":null,"transform":"<id>","tax_inclusion":null,"sign_convention":null}}],"unmapped_columns":["<header>"]}}

Columns (position, measured shape):
{chr(10).join(cols)}

Masked sample rows (personal data replaced; columns in the order above):
{sample}
"""


def float_free(f: Any) -> str:
    """Render a Fraction as 'n/d' — keeps floats out of every money-adjacent path, even prompt text."""
    return f"{f.numerator}/{f.denominator}"


def extract_json_object(text: str) -> str:
    """The first balanced JSON object in a model reply (models sometimes wrap it in prose or a code fence)."""
    start = text.find("{")
    if start < 0:
        raise MappingProposalFailed("the model did not return a JSON object")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    json.loads(candidate)
                except json.JSONDecodeError as exc:
                    raise MappingProposalFailed(f"the model's JSON was malformed: {exc}") from None
                return candidate
    raise MappingProposalFailed("the model's JSON object was not closed")


class LlmMappingProposer:
    def __init__(self, llm: LlmProvider, model: str) -> None:
        self._llm = llm
        self._model = model

    def __call__(self, inp: ProposerInput) -> str:
        try:
            reply = self._llm.complete(model=self._model, prompt=build_prompt(inp))
        except Exception as exc:  # noqa: BLE001 - a model that is down or refused is never a reason to guess a mapping
            raise MappingProposalFailed(f"the mapping model could not be reached: {type(exc).__name__}") from None
        return extract_json_object(reply)
