"""
Pipeline for NL -> FL statement generation and error classification.
Uses Kimina-Autoformalizer-7B to generate FL statements (ending with 'by sorry'),
then validates them with Lean 4 to classify statement-level errors only.

Error taxonomy (statement-level only):
  SUCCESS    - FL statement compiles with sorry
  SYNTACTIC  - Invalid Lean 4 grammar / parse error
  TYPE_ERROR - Type mismatch / typeclass failure
  TIMEOUT    - Lean verification timed out
  UNKNOWN    - Unclassified failure
"""

import subprocess, json, torch, os
from transformers import AutoModelForCausalLM, AutoTokenizer
from datasets import load_dataset
from collections import Counter

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USER  = "pooloom69"
GITHUB_REPO  = "autoformalization-error-taxonomy"
REPO_PATH    = "/tmp/mathlib_test/autoformalization-error-taxonomy"
MODEL_PATH   = "/tmp/kimina-autoformalizer-7b"
MATHLIB_PATH = "/tmp/mathlib_test/myproject"
RESULTS_PATH = f"{REPO_PATH}/results/results_autoformalizer_244.json"

os.makedirs(f"{REPO_PATH}/results", exist_ok=True)

# ─────────────────────────────────────────────
# GitHub push helper
# ─────────────────────────────────────────────
def git_push(message="Update results"):
    if not GITHUB_TOKEN:
        print("No GITHUB_TOKEN, skipping push")
        return
    subprocess.run(
        f'cd {REPO_PATH} && '
        f'git config --local user.email "pooloom69@gmail.com" && '
        f'git config --local user.name "pooloom69" && '
        f'git remote set-url origin https://{GITHUB_USER}:{GITHUB_TOKEN}@github.com/{GITHUB_USER}/{GITHUB_REPO}.git && '
        f'git add results/ && '
        f'git diff --cached --quiet || git commit -m "{message}" && '
        f'git push origin mathlib',
        shell=True, capture_output=True
    )
    print(f"GitHub push: {message}")

# ─────────────────────────────────────────────
# Model
# ─────────────────────────────────────────────
print("Loading Kimina-Autoformalizer-7B...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_PATH,
    dtype=torch.float16,
    device_map="auto"
)
print(f"Model loaded! Device: {next(model.parameters()).device}")

# ─────────────────────────────────────────────
# FL Statement Generation
# ─────────────────────────────────────────────
def generate_fl_statement(nl_problem: str, theorem_name: str) -> str:
    """Generate FL statement (ending with 'by sorry') from NL problem."""
    prompt = (
        f"Please autoformalize the following problem in Lean 4 with a header. "
        f"The theorem must end with ':= by sorry'. "
        f"Use the following theorem names: {theorem_name}.\n\n"
        f"{nl_problem}"
    )
    messages = [
        {"role": "system", "content": "You are an expert in mathematics and Lean 4."},
        {"role": "user",   "content": prompt}
    ]
    inputs = tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt"
    ).to(model.device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=512,
            do_sample=False,
        )
    generated = tokenizer.decode(
        outputs[0][inputs["input_ids"].shape[-1]:],
        skip_special_tokens=True
    ).strip()

    # Post-process: ensure statement ends with by sorry
    if generated.endswith(":="):
        generated = generated + " by sorry"
    elif "sorry" not in generated:
        generated = generated.rstrip() + " := by sorry"

    return generated

# ─────────────────────────────────────────────
# Lean Validation (sorry allowed)
# ─────────────────────────────────────────────
def run_lean(code: str, timeout: int = 60) -> dict:
    """Run Lean 4 with Mathlib; sorry is allowed (statement-level check only)."""
    lean_file = f"{MATHLIB_PATH}/test_autoform.lean"
    with open(lean_file, "w") as f:
        f.write(code)
    try:
        result = subprocess.run(
            ["lake", "env", "lean", lean_file],
            capture_output=True, text=True,
            timeout=timeout,
            cwd=MATHLIB_PATH
        )
        return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "TIMEOUT", "returncode": -1}

# ─────────────────────────────────────────────
# Error Classification (statement-level)
# ─────────────────────────────────────────────
SYNTACTIC_PATTERNS = [
    "unexpected token",
    "expected token",
    "unknown identifier",
    "unknownIdentifier",
]
TYPE_ERROR_PATTERNS = [
    "type mismatch",
    "Type mismatch",
    "application type mismatch",
    "failed to synthesize",
    "synthInstanceFailed",
    "Ambiguous term",
    "Unknown constant",
]

def classify_statement_error(output: dict) -> str:
    if output["stderr"] == "TIMEOUT":
        return "TIMEOUT"

    msg = output["stdout"] + output["stderr"]

    if output["returncode"] == 0:
        return "SUCCESS"

    for p in TYPE_ERROR_PATTERNS:
        if p in msg:
            return "TYPE_ERROR"

    for p in SYNTACTIC_PATTERNS:
        if p in msg:
            return "SYNTACTIC"

    return "UNKNOWN"

# ─────────────────────────────────────────────
# Main Pipeline
# ─────────────────────────────────────────────
ds = load_dataset("cat-searcher/minif2f-lean4")

# Resume support
if os.path.exists(RESULTS_PATH):
    with open(RESULTS_PATH) as f:
        results = json.load(f)
    start_idx = len(results)
    print(f"Resuming from {start_idx}/244...")
else:
    results = []
    start_idx = 0
    print("Starting fresh...")

MATHLIB_HEADER = "import Mathlib\nopen BigOperators Real Nat Topology\n\n"

for i, sample in enumerate(ds["test"]):
    if i < start_idx:
        continue

    print(f"\n[{i+1}/244] {sample['id']}")

    # Generate FL statement
    fl_generated = generate_fl_statement(
        nl_problem=sample["informal_stmt"],
        theorem_name=sample["id"]
    )
    print(f"FL: {fl_generated[:120]}")

    # Prepend Mathlib header if model didn't include it
    if "import Mathlib" in fl_generated:
        lean_code = fl_generated
    else:
        lean_code = MATHLIB_HEADER + fl_generated

    # Validate with Lean
    lean_out   = run_lean(lean_code, timeout=60)
    error_type = classify_statement_error(lean_out)
    print(f"Result: {error_type}")

    results.append({
        "id":           sample["id"],
        "nl":           sample["informal_stmt"],
        "fl_generated": fl_generated,
        "lean_code":    lean_code,
        "error_type":   error_type,
        "lean_output":  (lean_out["stdout"] + lean_out["stderr"])[:400]
    })

    # Save + push every 10
    if (i + 1) % 10 == 0:
        with open(RESULTS_PATH, "w") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        git_push(f"Autoformalizer results [{i+1}/244]")

        counter = Counter(r["error_type"] for r in results)
        print(f"\n--- Stats [{i+1}/244] ---")
        for k, v in sorted(counter.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")

# Final save + push
with open(RESULTS_PATH, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
git_push("Autoformalizer final results 244/244")

counter = Counter(r["error_type"] for r in results)
print("\n===== Final Statistics =====")
for k, v in sorted(counter.items(), key=lambda x: -x[1]):
    print(f"{k}: {v} ({v/len(results)*100:.1f}%)")
print(f"\nTotal: {len(results)} problems processed!")
