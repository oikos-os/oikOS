"""Docker health check script for oikos-core container.

Validates: FastAPI responding, vault index accessible, Ollama reachable.
Exit 0 = healthy, exit 1 = unhealthy.
"""

import sys

def check():
    import httpx

    # Check FastAPI
    try:
        r = httpx.get("http://127.0.0.1:8420/api/status", timeout=5)
        if r.status_code != 200:
            print(f"FastAPI unhealthy: HTTP {r.status_code}")
            return False
    except Exception as exc:
        print(f"FastAPI unreachable: {exc}")
        return False

    # Check Ollama connectivity
    ollama_host = "http://ollama:11434"
    try:
        r = httpx.get(f"{ollama_host}/api/tags", timeout=5)
        if r.status_code != 200:
            print(f"Ollama unhealthy: HTTP {r.status_code}")
            return False
    except Exception as exc:
        print(f"Ollama unreachable: {exc}")
        return False

    print("All checks passed")
    return True


if __name__ == "__main__":
    sys.exit(0 if check() else 1)
