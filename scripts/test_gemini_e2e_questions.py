"""Real Gemini Agent E2E Audit Script.

Executes the 8 mandatory audit questions against the real Gemini Agent
(google_genai with gemini-3.8-flash).
Traces:
- Configured LLM provider & model
- Tool calls selected & arguments
- Tool results from backend
- Final agent answer
- Grounding & uncertainty handling
"""

import os
import sys
import json
import uuid
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Force real google_genai provider and load .env
from dotenv import load_dotenv
load_dotenv()
os.environ["DATT_AGENT_LLM_PROVIDER"] = "google_genai"
os.environ["DATT_AGENT_LLM_MODEL"] = "gemini-3.8-flash"

from src.agent.llm import get_active_provider_info
from src.agent.graph import run_agent_message
from langgraph.checkpoint.memory import MemorySaver

QUESTIONS = [
    ("Q1", "Trong 7 ngày qua camera nào đông người nhất?"),
    ("Q2", "Camera cổng chính thường đông khách lúc mấy giờ?"),
    ("Q3", "Bãi xe A thường đông xe nhất vào thời điểm nào?"),
    ("Q4", "Ngày mai cổng chính dự kiến đông lúc nào?"),
    ("Q5", "Ngày mai có camera nào cần cảnh báo không?"),
    ("Q6", "Tại sao hệ thống dự báo ngày mai đông?"),
    ("Q7", "Nếu ngày mai đông thì tôi nên bố trí nhân sự thế nào?"),
    ("Q8", "Dữ liệu hiện tại đã đủ để dự báo chưa?"),
]

def main():
    print("=" * 80, flush=True)
    print("PHASE 8 — GEMINI AGENT E2E VERIFICATION", flush=True)
    print("=" * 80, flush=True)

    info = get_active_provider_info()
    print(f"Configured Provider: {info['configured_provider']}", flush=True)
    print(f"Actual Runtime:     {info['actual_runtime']}", flush=True)
    print(f"Model Name:         {info['model_name']}", flush=True)
    print(f"Has Gemini Key:     {info['has_gemini_key']}", flush=True)
    print(f"Is Mock:            {info['is_mock']}", flush=True)
    print("=" * 80, flush=True)

    checkpointer = MemorySaver()
    thread_id = f"test_thread_{uuid.uuid4().hex[:8]}"

    results = []
    output_path = "gemini_audit_results.json"

    for q_id, q_text in QUESTIONS:
        print(f"\n--- Testing {q_id}: '{q_text}' ---", flush=True)
        try:
            res = run_agent_message(
                content=q_text,
                thread_id=thread_id,
                user_id="audit_operator",
                is_authenticated=True,
                checkpointer=checkpointer,
            )
            print(f"Status: {res.get('status')}", flush=True)
            print(f"Tools Called: {res.get('tools_called')}", flush=True)
            rep = str(res.get('reply') or '')
            print(f"Reply: {rep[:150]}...", flush=True)
            results.append({
                "id": q_id,
                "question": q_text,
                "status": res.get("status"),
                "tools_called": res.get("tools_called"),
                "reply": res.get("reply"),
                "sources": res.get("sources"),
            })
        except Exception as exc:
            err_msg = str(exc)
            status_label = "BLOCKED (Quota Exhausted / 429)" if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg else "error"
            print(f"RESULT: {status_label} - {err_msg[:120]}", flush=True)
            results.append({
                "id": q_id,
                "question": q_text,
                "status": status_label,
                "error": err_msg,
            })

        # Save incrementally
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({
                "provider_info": info,
                "thread_id": thread_id,
                "results": results,
            }, f, ensure_ascii=False, indent=2)

    print(f"\nAll results saved to {output_path}", flush=True)

if __name__ == "__main__":
    main()
