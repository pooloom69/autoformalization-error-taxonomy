from transformers import AutoModelForCausalLM, AutoTokenizer
import torch
import json
import subprocess
import sys
import os
import time
from collections import Counter

sys.path.append('/ProofBridge/datasets_training/NuminaMath-LEAN-PF')
from getDataset import pairs

SAVE_DIR = '/ProofBridge/autoformalization-error-taxonomy/results/kimina_1.7B'
REPO_DIR = '/ProofBridge/autoformalization-error-taxonomy'
CHECKPOINT_FILE = f'{SAVE_DIR}/checkpoint_latest.json'
LEAN_PATH = '/root/.elan/bin/lean'
LAKE_PATH = '/root/.elan/bin/lake'
MATHLIB_PROJECT = '/ProofBridge/mathlib_project'

os.makedirs(SAVE_DIR, exist_ok=True)

# Verify Lean
print("Verifying Lean...")
result = subprocess.run([LEAN_PATH, '--version'], capture_output=True)
if result.returncode != 0:
    print("ERROR: Lean not found. Stopping.")
    sys.exit(1)
print("Lean OK!")

# Verify Lake
print("Verifying Lake...")
result = subprocess.run([LAKE_PATH, '--version'], capture_output=True)
if result.returncode != 0:
    print("ERROR: Lake not found. Stopping.")
    sys.exit(1)
print("Lake OK!")

# Load model
print("Loading model...")
tokenizer = AutoTokenizer.from_pretrained('AI-MO/Kimina-Prover-RL-1.7B')
model = AutoModelForCausalLM.from_pretrained(
    'AI-MO/Kimina-Prover-RL-1.7B',
    dtype=torch.float16,
    device_map='cuda'
)
print("Model loaded!")

def classify_error(error_msg):
    if 'type mismatch' in error_msg or 'has type' in error_msg:
        return 'type_error'
    elif 'tactic failed' in error_msg or 'maximum recursion' in error_msg:
        return 'prover_failure'
    elif 'timeout' in error_msg:
        return 'prover_timeout'
    elif 'expected' in error_msg or 'unknown identifier' in error_msg:
        return 'syntactic'
    elif 'unknown module' in error_msg or 'import' in error_msg.lower():
        return 'import_error'
    else:
        return 'other'

def lean_check(fl_code):
    """Run Lean via lake and return (error_type, error_message)."""
    try:
        test_file = f'{MATHLIB_PROJECT}/Test.lean'
        with open(test_file, 'w') as f:
            f.write(fl_code)
        # Use lake build instead of lean directly
        result = subprocess.run(
            [LAKE_PATH, 'build', 'Test'],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=MATHLIB_PROJECT
        )
        if result.returncode == 0:
            return 'success', ''
        else:
            error_msg = result.stderr + result.stdout
            error_type = classify_error(error_msg)
            return error_type, error_msg
    except subprocess.TimeoutExpired:
        return 'prover_timeout', 'timeout'
    except Exception as e:
        return 'lean_error', str(e)

def extract_lean_code(generated_text):
    if 'import Mathlib' in generated_text:
        return generated_text[generated_text.index('import Mathlib'):]
    elif 'theorem' in generated_text:
        return generated_text[generated_text.index('theorem'):]
    return None

def translate(nl):
    try:
        prompt = f"""Translate the following natural language theorem and proof to Lean 4.

{nl}

Lean 4 translation:"""
        inputs = tokenizer(prompt, return_tensors='pt').to('cuda')
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=512,
                temperature=0.6,
                do_sample=True
            )
        return tokenizer.decode(outputs[0], skip_special_tokens=True)
    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()
        print("GPU OOM - skipping")
        return None
    except Exception as e:
        print(f"Translation error: {e}")
        return None

def git_push(checkpoint_num):
    for attempt in range(3):
        try:
            subprocess.run(['git', 'add', '.'], cwd=REPO_DIR, check=True)
            subprocess.run(['git', 'commit', '-m', f'checkpoint {checkpoint_num}'], cwd=REPO_DIR, check=True)
            subprocess.run(['git', 'push'], cwd=REPO_DIR, check=True)
            print(f"GitHub push done: checkpoint {checkpoint_num}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Push attempt {attempt+1} failed: {e}")
            time.sleep(5)
    print("ERROR: GitHub push failed 3 times. Stopping.")
    sys.exit(1)

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, 'r') as f:
            results = json.load(f)
        print(f"Resuming from checkpoint: {len(results)} already done")
        return results
    return []

def print_stats(results):
    error_counts = Counter(r['error_type'] for r in results)
    total = len(results)
    print(f"\n=== Stats ({total} processed) ===")
    for error_type, count in error_counts.most_common():
        print(f"  {error_type}: {count} ({100*count/total:.1f}%)")
    print("================================\n")

# Load checkpoint
results = load_checkpoint()
done_indices = {r['index'] for r in results}

for i, (nl, fl_gold) in enumerate(pairs):
    if i in done_indices:
        print(f"Skipping {i+1}/{len(pairs)} (already done)")
        continue

    print(f"Processing {i+1}/{len(pairs)}...")

    # Step 1: Translate
    fl_generated_raw = translate(nl)
    if fl_generated_raw is None:
        results.append({
            'index': i,
            'nl': nl,
            'fl_gold': fl_gold,
            'fl_generated': None,
            'error_type': 'translation_failed',
            'error_message': 'model generated None'
        })
    else:
        # Step 2: Extract Lean code
        fl_generated = extract_lean_code(fl_generated_raw)
        if not fl_generated:
            results.append({
                'index': i,
                'nl': nl,
                'fl_gold': fl_gold,
                'fl_generated': fl_generated_raw,
                'error_type': 'empty_generation',
                'error_message': 'no lean code found in output'
            })
        else:
            # Step 3: Lean compiler check via lake
            error_type, error_msg = lean_check(fl_generated)
            results.append({
                'index': i,
                'nl': nl,
                'fl_gold': fl_gold,
                'fl_generated': fl_generated,
                'error_type': error_type,
                'error_message': error_msg
            })

    # Every 20 samples: save + push + stats + clear cache
    if (i+1) % 20 == 0:
        with open(CHECKPOINT_FILE, 'w') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        batch = results[-20:]
        batch_path = f'{SAVE_DIR}/batch_{i+1}.json'
        with open(batch_path, 'w') as f:
            json.dump(batch, f, indent=2, ensure_ascii=False)
        torch.cuda.empty_cache()
        print_stats(results)
        git_push(i+1)

# Final save
final_path = f'{SAVE_DIR}/results_final.json'
with open(final_path, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print_stats(results)
git_push('final')
print("All done!")
