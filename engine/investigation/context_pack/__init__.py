# Re-export AgentContextPack and TruncationConfig for backward compat
from engine.investigation.agent_models import AgentContextPack, TruncationConfig

from engine.investigation.context_pack._shared import (
    TRUNCATION_MARKER,
    CHARS_PER_TOKEN,
    estimate_tokens,
    head_tail_truncate,
)
from engine.investigation.context_pack.evidence import (
    get_all_canonical_finding_ids,
    get_artifact_backref,
    clear_canonical_ids_cache,
)
from engine.investigation.context_pack.claims import (
    build_context_pack_for_role,
    build_material_inventory_context_pack,
    build_review_context_pack,
)

__all__ = [
    # Agent models (re-exported for backward compat)
    "AgentContextPack",
    "TruncationConfig",
    # Constants
    "TRUNCATION_MARKER",
    "CHARS_PER_TOKEN",
    # Shared utilities
    "estimate_tokens",
    "head_tail_truncate",
    # Evidence / canonical finding IDs
    "get_all_canonical_finding_ids",
    "get_artifact_backref",
    "clear_canonical_ids_cache",
    # Context pack builders
    "build_context_pack_for_role",
    "build_material_inventory_context_pack",
    "build_review_context_pack",
]
