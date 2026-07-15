# medge-082-1 trace (reference)

## Objective
Distinguish gene-specific transcriptional programs from a shared response across KOs.

## Approach
1. log-CPM normalized 11215 genes x 6442 cells.
2. Per-KO DE vs control (Welch t, |t|>3). Naive ranking by n_deg puts
   KO_13 (685) and
   KO_05 (462) on top.
3. CRUCIAL CHECK: n_deg tracks mtDNA_copy_number. Control median mtDNA=372167.
   The top-DE KOs ['KO_13', 'KO_05', 'KO_03'] are strong mtDNA DEPLETERS (mtDNA well below control),
   so their large signatures are the SHARED mtDNA-depletion (integrated stress) response,
   not gene-specificity — their effect is inseparable from depletion (their cells barely
   overlap control mtDNA levels).
4. Gene-specific = substantial DE at NORMAL mtDNA. -> ['KO_11'] shows a large program while
   NOT depleting mtDNA (mtDNA ~ control) = genuine perturbation-specific response.

## Results
Gene-specific: ['KO_11']. Depletion-confounded (shared response, NOT gene-specific despite
largest raw DE): ['KO_13', 'KO_05', 'KO_03'].

## Limitations
mtDNA-depleting KOs cannot be cleanly separated into gene-specific vs shared components
from these data because their cells occupy a mtDNA range with little control overlap.

## References
Perturb-seq / mixscape (Papalexi 2021); integrated stress response to mtDNA depletion.
