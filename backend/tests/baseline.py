from tests.live import live_app

SCRIPT = [
    "I want to get started with large language model based papers. Where should I start?",
    "Which of those is the most foundational?",
    "Tell me more about the first one",
    "What about only papers after 2022 on this?",
    "Compare the first two",
    "What builds on the attention paper?",
    "Has anyone used retrieval to reduce hallucination in language models?",
    "I read the first one",
    "What did we talk about earlier regarding language models?",
]

with live_app() as (client, make, box):
    ada = make("ada")
    for message in SCRIPT:
        out = ada.chat(message)
        print("USER:", message)
        print("INTENT:", out["intent"].get("intent"), out["intent"].get("slots"))
        print("REPLY:", out["text"][:700])
        print("EVIDENCE:", [e.get("title") for e in out["evidence"]][:5])
        print()
    listing = ada.get(f"/students/{ada.id}/conversations")
    print("LIST:", listing)
    convo = ada.get(f"/students/{ada.id}/conversations/{ada.conversation}")
    print("TURNS:", len(convo["turns"]), [t["role"] for t in convo["turns"]])
