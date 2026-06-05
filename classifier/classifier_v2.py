import subprocess, json

def run_lean(code: str, timeout: int = 60) -> dict:
    with open("_tmp.lean", "w") as f:
        f.write(code)
    try:
        result = subprocess.run(
            ["lean", "_tmp.lean"],
            capture_output=True, text=True,
            timeout=timeout
        )
        return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "TIMEOUT", "returncode": -1}

def classify_error(output: dict) -> str:
    if output["stderr"] == "TIMEOUT":
        return "PROVER_FAILURE_timeout"
    msg = output["stdout"] + output["stderr"]
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
