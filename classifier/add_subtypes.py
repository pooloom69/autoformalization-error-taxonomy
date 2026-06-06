# (위 코드 붙여넣기)
import json
from collections import Counter

PROVER_SUBTYPES = {
    "unsolved goals": "incomplete_proof",
    "unexpected end of input": "incomplete_proof",
    "No goals to be solved": "over_applied_tactic",
    "linarith failed": "wrong_tactic",
    "omega could not prove": "wrong_tactic",
    "ring_nf` made no progress": "wrong_tactic",
    "failed to prove": "wrong_tactic",
    "Tactic `rfl` failed": "wrong_tactic",
    "Tactic `rewrite` failed": "wrong_tactic",
    "Tactic `apply` failed": "wrong_tactic",
    "push_neg` has been deprecated": "deprecated_tactic",
    "Did not find an occurrence": "wrong_tactic",
    "is not definitionally equal": "wrong_tactic",
    "counterexample": "wrong_tactic",
}

SYNTACTIC_SUBTYPES = {
    "Type mismatch": "type_error",
    "Ambiguous term": "ambiguous_term",
    "unexpected token": "invalid_syntax",
    "synthInstanceFailed": "typeclass_failure",
    "unknownIdentifier": "unknown_identifier",
    "unknown identifier": "unknown_identifier",
    "application type mismatch": "type_error",
    "Unknown constant": "unknown_constant",
    "failed to synthesize": "typeclass_failure",
}

with open('results/results_full_semantic.json') as f:
    results = json.load(f)

for r in results:
    error_type = r['error_type']
    msg = r.get('lean_output', '')
    pattern = r.get('matched_pattern', '')

    if error_type == 'PROVER_FAILURE':
        subtype = PROVER_SUBTYPES.get(pattern, 'unknown')
        r['error_subtype'] = subtype

    elif error_type == 'SYNTACTIC':
        subtype = SYNTACTIC_SUBTYPES.get(pattern, 'unknown')
        r['error_subtype'] = subtype

    elif error_type == 'SEMANTIC':
        r['error_subtype'] = 'semantic_mismatch'

    elif error_type == 'SUCCESS':
        r['error_subtype'] = 'success'

    elif error_type == 'SORRY':
        r['error_subtype'] = 'incomplete_sorry'

    else:
        r['error_subtype'] = 'unknown'

# Statistics
print("===== Error Type + Subtype Statistics =====\n")

# By type
counter = Counter(r['error_type'] for r in results)
for k, v in sorted(counter.items(), key=lambda x: -x[1]):
    print(f"{k}: {v} ({v/len(results)*100:.1f}%)")

print()

# By subtype
print("===== Subtype Breakdown =====\n")
by_type = {}
for r in results:
    t = r['error_type']
    s = r['error_subtype']
    if t not in by_type:
        by_type[t] = Counter()
    by_type[t][s] += 1

for t, subtypes in sorted(by_type.items()):
    print(f"{t}:")
    for s, count in sorted(subtypes.items(), key=lambda x: -x[1]):
        print(f"  {s}: {count}")
    print()

with open('results/results_full_semantic.json', 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("Saved!")