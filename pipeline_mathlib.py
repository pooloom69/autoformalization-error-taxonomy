import subprocess, json
from datasets import load_dataset

ds = load_dataset('cat-searcher/minif2f-lean4')

NEW_HEADER = """import Mathlib

open BigOperators
open Real
open Nat
open Topology"""

def fix_statement(code: str) -> str:
    code = code.replace('∑ x in ', '∑ x ∈ ')
    code = code.replace('∑ i in ', '∑ i ∈ ')
    code = code.replace('∏ x in ', '∏ x ∈ ')
    code = code.replace('∏ i in ', '∏ i ∈ ')
    return code

def run_lean_mathlib(code: str, timeout: int = 60) -> dict:
    lean_file = "/tmp/mathlib_test/test_pipeline.lean"
    with open(lean_file, "w") as f:
        f.write(code)
    try:
        result = subprocess.run(
            ["lake", "env", "lean", lean_file],
            capture_output=True, text=True,
            timeout=timeout,
            cwd="/tmp/mathlib_test"
        )
        return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "TIMEOUT", "returncode": -1}

def classify_error(output: dict) -> str:
    if output["stderr"] == "TIMEOUT":
        return "PROVER_FAILURE_timeout"
    msg = output["stdout"] + output["stderr"]
    if "object file" in msg and "does not exist" in msg:
        return "BUILD_ERROR"
    if "sorry" in msg and "warning" in msg:
        return "SORRY"
    if output["returncode"] == 0:
        return "SUCCESS"
    syntactic = [
        "synthInstanceFailed", "failed to synthesize",
        "unexpected token", "unknown identifier", "unknownIdentifier",
        "application type mismatch", "type mismatch",
    ]
    prover = [
        "omega could not prove", "unsolved goals",
        "unknown tactic", "tactic failed",
        "counterexample", "unknown constant",
        "Tactic `rfl` failed", "is not definitionally equal",
        "failed to prove",
    ]
    if any(p in msg for p in syntactic):
        return "SYNTACTIC"
    if any(p in msg for p in prover):
        return "PROVER_FAILURE"
    return "UNKNOWN"

results = []
for i, sample in enumerate(ds['test']):
    if i >= 10:
        break

    print(f"\n--- {sample['id']} ---")

    fl_statement = fix_statement(sample['formal_statement'])
    full_code = NEW_HEADER + '\n\n' + fl_statement

    lean_out = run_lean_mathlib(full_code, timeout=60)
    error_type = classify_error(lean_out)

    print(f"결과: {error_type}")
    print(f"Lean 출력: {(lean_out['stdout'] + lean_out['stderr'])[:150]}")

    results.append({
        "id": sample['id'],
        "error_type": error_type,
        "lean_output": (lean_out['stdout'] + lean_out['stderr'])[:300]
    })

print("\n===== 최종 결과 =====")
for r in results:
    print(f"{r['id']}: {r['error_type']}")

with open("/tmp/mathlib_test/results_mathlib.json", "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("\n저장 완료!")
