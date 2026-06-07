import subprocess, json, torch, os
from transformers import AutoModelForCausalLM, AutoTokenizer
from datasets import load_dataset
from collections import Counter

# GitHub configuration
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USER = "pooloom069"
GITHUB_REPO = "autoformalization-error-taxonomy"
REPO_PATH = "/tmp/mathlib_test/autoformalization-error-taxonomy"

# Auto-create results directory
os.makedirs(f"{REPO_PATH}/results", exist_ok=True)

def git_push(message="Update results"):
    if not GITHUB_TOKEN:
        print("No GITHUB_TOKEN found, skipping push")
        return
    subprocess.run(
        f'cd {REPO_PATH} && '
        f'git config --local user.email "pooloom069@gmail.com" && '
        f'git config --local user.name "pooloom069" && '
        f'git remote set-url origin https://{GITHUB_USER}:{GITHUB_TOKEN}@github.com/{GITHUB_USER}/{GITHUB_REPO}.git && '
        f'git add results/ && '
        f'git diff --cached --quiet || git commit -m "{message}" && '
        f'git push origin mathlib',
        shell=True, capture_output=True
    )
    print(f"GitHub push complete: {message}")

print("Loading model...")
model_path = "/tmp/kimina-prover-1.7b"
tokenizer = AutoTokenizer.from_pretrained(model_path)
model = AutoModelForCausalLM.from_pretrained(
    model_path,
    dtype=torch.float16,
    device_map="auto"
)
print(f"Model loaded! Device: {next(model.parameters()).device}")

ds = load_dataset('cat-searcher/minif2f-lean4')

NEW_HEADER = """import Mathlib
open BigOperators
open Real
open Nat
open Topology"""

def fix_statement(code):
    # Fix deprecated Lean 4 syntax
    code = code.replace('∑ x in ', '∑ x ∈ ')
    code = code.replace('∑ i in ', '∑ i ∈ ')
    code = code.replace('∏ x in ', '∏ x ∈ ')
    code = code.replace('∏ i in ', '∏ i ∈ ')
    return code

def extract_proof(generated):
    # Extract only the tactic proof, removing natural language explanation
    lines = generated.split('\n')
    proof_lines = []
    for line in lines:
        if any(line.startswith(kw) for kw in [
            'The ', 'This ', 'Let', 'In ', 'First', 'Note',
            'We ', 'Now ', 'Here', 'So ', 'Since'
        ]):
            break
        proof_lines.append(line)
    return '\n'.join(proof_lines).strip()

def generate_proof(nl_problem, fl_statement):
    # Generate Lean 4 proof using the model
    prompt = f"Problem: {nl_problem}\nFormal:\n{fl_statement}"
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=512,
            do_sample=False,
        )
    raw = tokenizer.decode(
        outputs[0][inputs["input_ids"].shape[-1]:],
        skip_special_tokens=True
    ).strip()
    return extract_proof(raw)

def run_lean_mathlib(code, timeout=120):
    # Run Lean 4 with Mathlib and return output
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

def classify_error(output):
    # Classify Lean output into error taxonomy
    if output["stderr"] == "TIMEOUT":
        return "PROVER_FAILURE_timeout"
    msg = output["stdout"] + output["stderr"]
    if "object file" in msg and "does not exist" in msg:
        return "BUILD_ERROR"
    if "sorry" in msg and "warning" in msg:
        return "SORRY"
    if output["returncode"] == 0:
        return "SUCCESS"

    # Syntactic error patterns
    syntactic = [
        "synthInstanceFailed", "failed to synthesize",
        "unexpected token", "unknown identifier", "unknownIdentifier",
        "application type mismatch", "type mismatch",
        "Type mismatch", "Ambiguous term",
    ]
    # Prover failure patterns
    prover = [
        "omega could not prove", "unsolved goals",
        "unknown tactic", "tactic failed",
        "counterexample", "unknown constant",
        "Tactic `rfl` failed", "is not definitionally equal",
        "failed to prove", "Tactic `rewrite` failed",
        "Did not find an occurrence", "unexpected end of input",
        "linarith failed", "push_neg` has been deprecated",
        "Tactic `apply` failed", "ring_nf` made no progress",
        "No goals to be solved",
    ]
    if any(p in msg for p in syntactic):
        return "SYNTACTIC"
    if any(p in msg for p in prover):
        return "PROVER_FAILURE"
    return "UNKNOWN"

# Load existing results and resume from where we left off
results_path = f"{REPO_PATH}/results/results_full.json"
if os.path.exists(results_path):
    with open(results_path) as f:
        results = json.load(f)
    start_idx = len(results)
    print(f"Resuming from {start_idx}/244...")
else:
    results = []
    start_idx = 0
    print("Starting fresh...")

# Run pipeline on full MiniF2F test set (244 problems)
for i, sample in enumerate(ds['test']):
    if i < start_idx:
        continue

    print(f"\n[{i+1}/244] {sample['id']}")

    # Prepare formal statement
    fl_statement = fix_statement(sample['formal_statement']).replace(':= sorry', ':= by')

    # Generate proof with model
    proof = generate_proof(sample['informal_stmt'], fl_statement)
    print(f"proof: {proof[:80]}")

    # Run Lean verification
    full_code = NEW_HEADER + '\n\n' + fl_statement + '\n  ' + proof
    lean_out = run_lean_mathlib(full_code, timeout=120)
    error_type = classify_error(lean_out)
    print(f"result: {error_type}")

    results.append({
        "id": sample['id'],
        "nl": sample['informal_stmt'],
        "fl_statement": fl_statement,
        "generated_proof": proof,
        "error_type": error_type,
        "lean_output": (lean_out['stdout'] + lean_out['stderr'])[:300]
    })

    # Save and push every 10 problems
    if (i + 1) % 10 == 0:
        with open(results_path, "w") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        git_push(f"Update results [{i+1}/244]")

        # Print intermediate statistics
        counter = Counter(r['error_type'] for r in results)
        print(f"\n--- Intermediate stats [{i+1}/244] ---")
        for k, v in sorted(counter.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")

# Final save and push
with open(results_path, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
git_push("Final results 244/244")

# Print final statistics
counter = Counter(r['error_type'] for r in results)
print("\n===== Final Statistics =====")
for k, v in sorted(counter.items(), key=lambda x: -x[1]):
    print(f"{k}: {v} ({v/len(results)*100:.1f}%)")
print(f"\nTotal: {len(results)} problems processed!")
