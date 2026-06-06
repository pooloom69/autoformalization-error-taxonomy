# classifier/semantic_check.py

import json
from anthropic import Anthropic

client = Anthropic()

SYSTEM_PROMPT = """You are an expert in formal mathematics and Lean 4.
Your task is to check whether a formal Lean 4 statement correctly captures 
the meaning of a natural language math problem.

Answer with:
- MATCH: if the formal statement correctly expresses the NL problem
- MISMATCH: if there is a semantic difference
- REASON: brief explanation of why

Format your response as:
VERDICT: MATCH or MISMATCH
REASON: explanation"""

def check_semantic(nl_problem: str, fl_statement: str) -> dict:
    """Check if FL statement matches NL problem semantically."""
    
    prompt = f"""Natural Language Problem:
{nl_problem}

Formal Lean 4 Statement:
{fl_statement}

Does the formal statement correctly capture the meaning of the natural language problem?
Focus on:
1. Quantifiers (∀ vs ∃)
2. Missing conditions
3. Type mismatches (ℕ vs ℝ vs ℤ)
4. Incomplete answer encoding"""

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    
    text = response.content[0].text
    verdict = "MATCH" if "VERDICT: MATCH" in text else "MISMATCH"
    reason = text.split("REASON:")[-1].strip() if "REASON:" in text else text
    
    return {
        "verdict": verdict,
        "reason": reason,
        "raw": text
    }

# Load results
with open('results/results_full.json') as f:
    results = json.load(f)

# Only check PROVER_FAILURE cases
prover_failures = [r for r in results if r['error_type'] == 'PROVER_FAILURE']
print(f"Checking {len(prover_failures)} PROVER_FAILURE cases...\n")

semantic_errors = []
for i, r in enumerate(prover_failures):
    print(f"[{i+1}/{len(prover_failures)}] {r['id']}")
    
    result = check_semantic(r['nl'], r['fl_statement'])
    r['semantic_check'] = result
    
    if result['verdict'] == 'MISMATCH':
        r['error_type'] = 'SEMANTIC'
        semantic_errors.append(r)
        print(f"  → SEMANTIC: {result['reason'][:80]}")
    else:
        print(f"  → PROVER_FAILURE (confirmed)")

# Final statistics
from collections import Counter
counter = Counter(r['error_type'] for r in results)
print("\n===== Final Statistics =====")
for k, v in sorted(counter.items(), key=lambda x: -x[1]):
    print(f"  {k}: {v} ({v/len(results)*100:.1f}%)")

print(f"\nSemantic errors found: {len(semantic_errors)}")
for r in semantic_errors:
    print(f"  {r['id']}: {r['semantic_check']['reason'][:80]}")

# Save
with open('results/results_full_semantic.json', 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("\nSaved to results_full_semantic.json!")