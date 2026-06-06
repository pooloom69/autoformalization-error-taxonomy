import subprocess, json, torch, os
from transformers import AutoModelForCausalLM, AutoTokenizer
from datasets import load_dataset
from collections import Counter

# GitHub 설정
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USER = "pooloom069"
GITHUB_REPO = "autoformalization-error-taxonomy"
REPO_PATH = "/tmp/mathlib_test/autoformalization-error-taxonomy"

def git_push(message="Update results"):
    if not GITHUB_TOKEN:
        print("GITHUB_TOKEN 없음, push 스킵")
        return
    subprocess.run(
        f'cd {REPO_PATH} && '
        f'git remote set-url origin https://{GITHUB_USER}:{GITHUB_TOKEN}@github.com/{GITHUB_USER}/{GITHUB_REPO}.git && '
        f'git add results/ && '
        f'git commit -m "{message}" && '
        f'git push origin mathlib',
        shell=True, capture_output=True
    )
    print(f"GitHub push 완료: {message}")

print("모델 로딩 중...")
model_path = "/tmp/kimina-prover-1.7b"
tokenizer = AutoTokenizer.from_pretrained(model_path)
model = AutoModelForCausalLM.from_pretrained(
    model_path,
    dtype=torch.float16,
    device_map="auto"
)
print(f"완료! Device: {next(model.parameters()).device}")

ds = load_dataset('cat-searcher/minif2f-lean4')

NEW_HEADER = """import Mathlib
open BigOperators
open Real
open Nat
open Topology"""

def fix_statement(code):
    code = code.replace('∑ x in ', '∑ x ∈ ')
    code = code.replace('∑ i in ', '∑ i ∈ ')
    code = code.replace('∏ x in ', '∏ x ∈ ')
    code = code.replace('∏ i in ', '∏ i ∈ ')
    return code

def extract_proof(generated):
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
        "failed to prove", "Tactic `rewrite` failed",
        "Did not find an occurrence", "unexpected end of input",
    ]
    if any(p in msg for p in syntactic):
        return "SYNTACTIC"
    if any(p in msg for p in prover):
        return "PROVER_FAILURE"
    return "UNKNOWN"

results = []
for i, sample in enumerate(ds['test']):
    print(f"\n[{i+1}/244] {sample['id']}")
    fl_statement = fix_statement(sample['formal_statement']).replace(':= sorry', ':= by')
    proof = generate_proof(sample['informal_stmt'], fl_statement)
    print(f"proof: {proof[:80]}")
    full_code = NEW_HEADER + '\n\n' + fl_statement + '\n  ' + proof
    lean_out = run_lean_mathlib(full_code, timeout=120)
    error_type = classify_error(lean_out)
    print(f"결과: {error_type}")
    results.append({
        "id": sample['id'],
        "nl": sample['informal_stmt'],
        "fl_statement": fl_statement,
        "generated_proof": proof,
        "error_type": error_type,
        "lean_output": (lean_out['stdout'] + lean_out['stderr'])[:300]
    })

    # 10개마다 저장 + push
    if (i + 1) % 10 == 0:
        with open(f"{REPO_PATH}/results/results_full.json", "w") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        git_push(f"Update results [{i+1}/244]")
        
        # 중간 통계
        counter = Counter(r['error_type'] for r in results)
        print(f"\n--- [{i+1}/244] 중간 통계 ---")
        for k, v in sorted(counter.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}개")

# 최종 저장 + push
with open(f"{REPO_PATH}/results/results_full.json", "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
git_push("Final results 244/244")

counter = Counter(r['error_type'] for r in results)
print("\n===== 최종 통계 =====")
for k, v in sorted(counter.items(), key=lambda x: -x[1]):
    print(f"{k}: {v}개 ({v/len(results)*100:.1f}%)")
print(f"\n총 {len(results)}개 처리 완료!")
