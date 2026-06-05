# Autoformalization Error Taxonomy

Error taxonomy for Lean 4 autoformalization pipeline.

## Structure
- classifier/ : Error classification logic
- results/    : Test results
- notebooks/  : Colab notebooks

## Error Types
- SUCCESS        : Proof verified
- SORRY          : Incomplete proof
- SYNTACTIC      : Lean 4 grammar error
- PROVER_FAILURE : Tactic failed / timeout
- SEMANTIC       : Semantic mismatch (requires LLM check)

## Accuracy
classifier_v1.0: 14/14 (100%)
