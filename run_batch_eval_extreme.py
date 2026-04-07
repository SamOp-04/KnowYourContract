import os
import time
import uuid

import requests

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "").strip()
EVAL_CHAT_ID = os.getenv("EXTREME_EVAL_CHAT_ID", "extreme_eval_chat")

QUESTIONS = [
    "What are all the hourly rate tiers for Key Personnel and at what hour thresholds do they change?",
    "What are the different hotel rate limits and when does each apply?",
    "What are all the monetary caps in this agreement? List every dollar figure mentioned.",
    "What triggers each different type of termination, and what payment is owed in each case?",
    "What are the different notice periods required for different actions in this contract?",
    "The contract has both a liability cap and exceptions to that cap - what is the cap, and what are ALL the exceptions?",
    "Consultant's IP indemnification is said to be unlimited in Section 7.D but a general cap exists in Section 8.B - which governs IP claims?",
    "Can the monthly retainer be applied against hourly fees?",
    "Does the non-compete apply if Company terminates for convenience?",
    "What happens if a Force Majeure Event lasts more than 90 days AND there is an active unpaid invoice?",
    "If Company suspends an SOW for 100 days, what rights does Consultant have?",
    "What obligations survive termination of this agreement, and for how long does each survive?",
    "Under what conditions can Company conduct more than one audit per year?",
    "What is the penalty if Consultant misses the 5th business day invoice deadline?",
    "Does this contract require Consultant to carry Directors & Officers (D&O) insurance?",
    "What happens if both Key Personnel and a Force Majeure Event occur simultaneously?",
    "Is there a minimum number of hours Consultant must bill per month?",
    "How many days notice must Consultant give to terminate for convenience?",
    "How long must records be retained after final payment?",
    "What is the liquidated damages amount for a non-compete breach, and is it per breach or aggregate?",
    "Within how many hours must a data breach be reported to Company?",
    "How many depositions is each party entitled to in arbitration discovery?",
    "Under what conditions is Consultant entitled to business class air travel?",
    "When does the overbilling audit cost shift to Consultant?",
    "What conditions must be met before Consultant can suspend services for non-payment?",
    "What happens to open source components - when are they allowed and what must be delivered with them?",
    "Who are the Key Personnel and what are their specific roles?",
    "Who signed this agreement and on behalf of which entities?",
    "Which companies are currently on the Restricted Competitors list?",
    "Who must approve Change Orders exceeding $50,000?"
]

def get_latest_extreme_contract(session: "requests.Session", chat_id: str) -> str | None:
    try:
        res = session.get(f"{API_BASE_URL}/contracts", params={"chat_id": chat_id}, timeout=60)
        res.raise_for_status()
        contracts = res.json().get("contracts", [])
        for c in reversed(contracts):
            contract_id = str(c.get("contract_id", ""))
            display_name = str(c.get("display_name", ""))
            source_name = str(c.get("source_name", ""))
            haystack = f"{contract_id} {display_name} {source_name}".lower()
            if "extremetest" in haystack or "extreme-test" in haystack:
                return c["contract_id"]
    except Exception as e:
        print(f"Error fetching contracts: {e}")
    return None


def upload_extreme_contract(session: "requests.Session", chat_id: str) -> str | None:
    print("Uploading ExtremeTest-Contract.pdf...")
    try:
        with open("ExtremeTest-Contract.pdf", "rb") as file_handle:
            response = session.post(
                f"{API_BASE_URL}/upload",
                data={"chat_id": chat_id},
                files={"file": ("ExtremeTest-Contract.pdf", file_handle, "application/pdf")},
                timeout=300,
            )
        response.raise_for_status()
        payload = response.json()

        contract_id = payload.get("contract_id")
        if contract_id:
            return str(contract_id)

        uploads = payload.get("uploads", [])
        if isinstance(uploads, list) and uploads:
            return str(uploads[0].get("contract_id", "")) or None
    except Exception as e:
        print(f"Failed to upload: {e}")

    return None

def main():
    chat_id = str(EVAL_CHAT_ID or "").strip() or f"extreme_eval_{uuid.uuid4().hex[:8]}"
    session = requests.Session()
    if API_AUTH_TOKEN:
        session.headers.update({"x-api-key": API_AUTH_TOKEN})

    contract_id = get_latest_extreme_contract(session=session, chat_id=chat_id)
    if not contract_id:
        contract_id = upload_extreme_contract(session=session, chat_id=chat_id)
    
    print(f"Using contract_id: {contract_id}")

    results = []
    
    with open("extreme_eval_results.md", "w", encoding="utf-8") as f:
        f.write("# ExtremeTest Contract Evaluation Results\n\n")

    for i, q in enumerate(QUESTIONS):
        print(f"[{i+1}/{len(QUESTIONS)}] Asking: {q}")
        try:
            res = session.post(
                f"{API_BASE_URL}/ask",
                json={"question": q, "contract_id": contract_id, "chat_id": chat_id},
                timeout=180,
            )
            res.raise_for_status()
            data = res.json()
            answer = data.get("answer", "No answer")
            results.append({
                "question": q,
                "answer": answer
            })
            print(f"Answer: {answer[:100]}...\n")
        except Exception as e:
            print(f"Error: {e}")
            answer = f"ERROR: {e}"
            results.append({
                "question": q,
                "answer": answer
            })
            time.sleep(2)
            
        with open("extreme_eval_results.md", "a", encoding="utf-8") as f:
            f.write(f"### Q: {q}\n**A:** {answer}\n\n---\n")

    print("Done! Results saved to extreme_eval_results.md")

if __name__ == "__main__":
    main()
