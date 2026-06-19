"""Ground truth → detection capability pipeline.

Transforms PubPeer posts and manual annotations into structured claims,
maps them to the capability taxonomy, identifies detection gaps,
generates design specifications, and enforces anti-overfitting rules.

5-phase pipeline:
  Phase 1: PARSE + MAP  (parser.py + mapper.py)
  Phase 2: GAP ANALYSIS (gap_analyzer.py)
  Phase 3: DESIGN       (design_spec.py)
  Phase 5: VERIFY       (anti_overfit.py)
"""

__version__ = "0.1.0"
