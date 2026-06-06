import json
from collections import Counter

# Load results
with open('results/results_full.json') as f:
    results = json.load(f)

# Error patterns with reasons
SYNTACTIC_PATTERNS = {
    "Type mismatch": "Type mismatch between expected and given type",
    "Ambiguous term": "Term has multiple possible interpretations",
    "unexpected token": "Invalid Lean 4 syntax token",
    "synthInstanceFailed": "Type class instance synthesis failed",
    "unknownIdentifier": "Identifier not found in scope",
    "unknown identifier": "Identifier not found in scope",
    "application type mismatch": "Function applied to argument of wrong type",
    "Unknown constant": "Constant not found in Lean 4 / Mathlib",
    "failed to synthesize": "Type class instance could not be synthesized",
}

PROVER_PATTERNS = {
    "linarith failed": "Linear arithmetic tactic could not find contradiction",
    "omega could not prove": "Integer arithmetic tactic failed",
    "unsolved goals": "Proof incomplete, goals remain",
    "push_neg` has been deprecated": "Deprecated tactic used (push_neg → push Not)",
    "push Not": "Deprecated tactic used (push_neg → push Not)",
    "Tactic `rfl` failed": "Reflexivity failed, terms not definitionally equal",
    "Tactic `rewrite` failed": "Rewrite tactic failed, pattern not found",
    "Tactic `apply` failed": "Apply tactic failed, conclusion could not be unified",
    "is not definitionally equal": "Terms are not definitionally equal",
    "Did not find an occurrence": "Rewrite pattern not found in expression",
    "unexpected end of input": "Proof incomplete, unexpected end",
    "unknown tactic": "Tactic not recognized",
    "tactic failed": "Tactic execution failed",
    "counterexample": "Counterexample found, statement is false",
    "unknown constant": "Constant not found",
    "failed to prove": "Proof attempt failed",
    "ring_nf` made no progress": "Ring normalization made no progress",
    "No goals to be solved": "Tactic applied after proof already complete",
    "Function expected": "Term used as function but is not a function type",
}

def classify_with_reason(lean_output, current_type):
    """Classify error with detailed reason and matched pattern."""
    msg = lean_output

    # Already SUCCESS or SORRY - no change needed
    if current_type in ["SUCCESS", "SORRY", "BUILD_ERROR", "PROVER_FAILURE_timeout"]:
        return current_type, None, None

    # Check syntactic patterns
    for pattern, reason in SYNTACTIC_PATTERNS.items():
        if pattern in msg:
            return "SYNTACTIC", reason, pattern

    # Check prover patterns
    for pattern, reason in PROVER_PATTERNS.items():
        if pattern in msg:
            return "PROVER_FAILURE", reason, pattern

    return "UNKNOWN", "No matching pattern found", None

# Reclassify all results
print("=== Reclassifying results ===\n")
changes = []

for r in results:
    old_type = r['error_type']
    new_type, reason, pattern = classify_with_reason(
        r.get('lean_output', ''),
        old_type
    )

    # Add reason fields
    r['error_reason'] = reason
    r['matched_pattern'] = pattern

    # Track changes
    if old_type != new_type:
        r['error_type'] = new_type
        changes.append({
            'id': r['id'],
            'old': old_type,
            'new': new_type,
            'reason': reason,
            'pattern': pattern
        })

# Print changes
print(f"Changed {len(changes)} classifications:\n")
for c in changes:
    print(f"  {c['id']}")
    print(f"    {c['old']} → {c['new']}")
    print(f"    Pattern: {c['pattern']}")
    print(f"    Reason:  {c['reason']}")
    print()

# Final statistics
print("===== Final Statistics =====")
counter = Counter(r['error_type'] for r in results)
for k, v in sorted(counter.items(), key=lambda x: -x[1]):
    print(f"  {k}: {v} ({v/len(results)*100:.1f}%)")

# Check remaining UNKNOWNs
unknowns = [r for r in results if r['error_type'] == 'UNKNOWN']
if unknowns:
    print(f"\nRemaining UNKNOWN ({len(unknowns)}):")
    for r in unknowns:
        print(f"  {r['id']}: {r['lean_output'][:100]}")

# Save
with open('results/results_full.json', 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("\nSaved!")