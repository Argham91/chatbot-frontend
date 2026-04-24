'''
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
import logging

app = FastAPI(title="Enterprise Agent Hub")

logging.basicConfig(level=logging.INFO)

# simple in-memory session store
CHAT_MEMORY = {}

class ChatRequest(BaseModel):
    question: str
    session_id: str
    user_role: str   

@app.post("/chat")
async def chat(request: ChatRequest):

    from agent import app as graph_app

    history = CHAT_MEMORY.get(request.session_id, [])
    state = {
        "question": request.question,
        "chat_history": history,
        "user_role": request.user_role,
        "department": "",
        "sql_query": "",
        "db_result": "",
        "final_answer": "",
        "retry_count": 0
}

    result = graph_app.invoke(state)

    # update memory
    history.append(request.question)
    history.append(result.get("final_answer"))
    CHAT_MEMORY[request.session_id] = history[-10:]

    logging.info(f"Final Answer: {result.get('final_answer')}")

    return result

# ================= STREAMING =================
@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):

    from agent import app as graph_app

    state = {
        "question": request.question,
        "chat_history": CHAT_MEMORY.get(request.session_id, []),
        "user_role": request.user_role,
        "department": "",
        "sql_query": "",
        "db_result": "",
        "final_answer": "",
        "retry_count": 0
    }

    def stream():
        for step in graph_app.stream(state):
            yield str(step) + "\n"

    return stream()
'''

from fastapi import FastAPI
from mock_db import get_messages, add_message

app = FastAPI()

@app.get("/messages")
def fetch_messages():
    return get_messages()

@app.post("/messages")
def create_message(msg: dict):
    return add_message(msg)