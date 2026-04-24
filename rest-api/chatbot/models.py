"""
chatbot/models.py
Pydantic request / response models for the IMOS AI Chatbot.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class ChatHistoryMessage(BaseModel):
    """Single message in the conversation history sent from frontend."""
    role: str       # "user" or "assistant"
    content: str    # plain text representation of the message


class ChatRequest(BaseModel):
    """Request body for POST /chatbot/chat"""
    message: str
    session_id: str
    history: List[ChatHistoryMessage] = []


# ---------------------------------------------------------------------------
# Response block types — Claude returns structured JSON with these blocks.
# ---------------------------------------------------------------------------

class ChatBlock(BaseModel):
    """
    A single renderable unit inside a chat response.

    type = "text"  → content field holds plain text / markdown
    type = "table" → headers + rows
    type = "chart" → chart_type, title, x_key, data, series
    """
    type: str                                       # "text" | "table" | "chart"

    # text block
    content: Optional[str] = None

    # table block
    headers: Optional[List[str]] = None
    rows: Optional[List[List[Any]]] = None

    # chart block
    chart_type: Optional[str] = None               # "bar" | "line" | "pie"
    title: Optional[str] = None
    x_key: Optional[str] = None                    # key used for x-axis / pie label
    data: Optional[List[Dict[str, Any]]] = None    # array of data objects
    series: Optional[List[Dict[str, str]]] = None  # [{key, label, color}]


class ChatResponse(BaseModel):
    """Response body returned to frontend from POST /chatbot/chat"""
    blocks: List[ChatBlock]
    session_id: str
    raw_text: Optional[str] = None  # first 500 chars of Claude raw output (debug)
