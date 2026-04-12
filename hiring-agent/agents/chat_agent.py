"""
agents/chat_agent.py
═══════════════════════════════════════════════════════
HireIQ Platform Assistant — RAG Chatbot Agent.

PURPOSE
────────
This agent answers user questions about the HireIQ platform:
  - "How do I upload a resume?"
  - "What does the AI Detection feature do?"
  - "My file was rejected — why?"
  - "Explain the scoring system to me"

RAG ARCHITECTURE: Keyword-Filtered In-Context RAG
──────────────────────────────────────────────────
1. User sends a message.
2. retrieve() scores every KB entry by tag-keyword overlap (microseconds, zero API cost).
3. Top 4 entries are formatted as a context block.
4. Context + conversation history (last 8 turns) + user message → LLM prompt.
5. LLM (llama-3.3-70b-versatile) generates a response.
6. Response is streamed back token by token via an async generator.
7. Conversation history is updated for the next turn.

WHY llama-3.3-70b-versatile?
──────────────────────────────
Best instruction-following + reasoning model on Groq's free tier.
Can explain complex topics simply ("like explaining to a 10-year-old"),
step-by-step, with clear language. Used for both scoring and orchestration
in this project already.

STREAMING
──────────
Uses Groq's async streaming API. Each chunk is a JSON-encoded SSE event:
  data: {"chunk": "Hello"}
  data: {"chunk": " world"}
  data: [DONE]
The FastAPI endpoint wraps this in a StreamingResponse with text/event-stream
content type. The frontend reads it with fetch() + ReadableStream.

CONVERSATION HISTORY
─────────────────────
Stored in-memory as a dict: session_id → list of {role, content} dicts.
Max 8 turns (16 messages) kept per session to bound token usage.
Sessions expire after MAX_SESSION_AGE_MINUTES of inactivity.
"""

from __future__ import annotations

import json
import os
import time
from typing import AsyncGenerator

from groq import AsyncGroq

from connectors.knowledge_base import format_context, retrieve
from utils.logger import logger

# ─── Config ──────────────────────────────────────────────────────────────────

_CHAT_MODEL = os.getenv("GROQ_CHATBOT", "llama-3.3-70b-versatile")

# Max turns (user + assistant pairs) to keep in history.
# 8 pairs = 16 messages. Keeps prompt ~2K tokens max for history portion.
_MAX_HISTORY_TURNS = 8

# Sessions older than this (in minutes) are purged on next access.
_MAX_SESSION_AGE_MINUTES = 60

# ─── System Prompt ────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are the HireIQ Assistant — a friendly, helpful AI guide for the HireIQ \
Autonomous Hiring Platform.

YOUR ROLE:
- Answer questions about how to USE the HireIQ platform.
- Explain what features do and how they work.
- Help users troubleshoot problems step by step.
- Explain concepts clearly enough that anyone — even someone completely new \
to AI or hiring software — can understand them.

YOUR PERSONALITY:
- Warm, patient, and encouraging. Never make the user feel dumb.
- Simple language first. Only use technical terms if needed, and always \
explain them when you do.
- Step-by-step when explaining how to do something.
- Concise — don't pad responses. Answer what was asked, then stop.
- When you don't know something, say so honestly and suggest where they \
might find the answer.

WHAT YOU KNOW:
You have access to a knowledge base (shown below as CONTEXT). Use it as \
your primary source of truth. If the answer is in the context, use it \
directly. If the question is beyond the context, use your general knowledge \
about AI hiring tools and hiring processes.

WHAT YOU DON'T DO:
- Don't make up specific numbers, thresholds, or feature details that \
aren't in the context.
- Don't pretend to have real-time data (like who's currently shortlisted).
- Don't discuss topics completely unrelated to HireIQ or hiring.

FORMAT:
- Use markdown formatting: **bold** for important terms, bullet points \
for steps or lists, and code blocks for IDs or technical strings.
- Keep responses focused — 3-5 sentences for simple questions, step-by-step \
numbered lists for how-to questions.
"""

# ─── Conversation Store ───────────────────────────────────────────────────────

# session_id → {"history": [...], "last_access": float(unix_ts)}
_sessions: dict[str, dict] = {}


def _get_history(session_id: str) -> list[dict]:
    """Return conversation history for a session (creates it if new)."""
    now = time.time()
    if session_id not in _sessions:
        _sessions[session_id] = {"history": [], "last_access": now}
    _sessions[session_id]["last_access"] = now
    return _sessions[session_id]["history"]


def _save_turn(session_id: str, user_msg: str, assistant_msg: str) -> None:
    """Append a completed turn to history, capping at MAX_HISTORY_TURNS."""
    history = _get_history(session_id)
    history.append({"role": "user",      "content": user_msg})
    history.append({"role": "assistant", "content": assistant_msg})
    # Keep only the most recent turns
    if len(history) > _MAX_HISTORY_TURNS * 2:
        _sessions[session_id]["history"] = history[-(  _MAX_HISTORY_TURNS * 2):]


def purge_expired_sessions() -> int:
    """Remove sessions that haven't been accessed recently. Returns count removed."""
    cutoff = time.time() - (_MAX_SESSION_AGE_MINUTES * 60)
    expired = [sid for sid, data in _sessions.items() if data["last_access"] < cutoff]
    for sid in expired:
        del _sessions[sid]
    if expired:
        logger.info(f"CHATBOT | Purged {len(expired)} expired sessions")
    return len(expired)


# ─── Chat Agent ───────────────────────────────────────────────────────────────

class ChatAgent:
    """
    RAG-powered chatbot agent for the HireIQ platform.

    Two public methods:
      stream(message, session_id)  → async generator of SSE-formatted strings
      chat(message, session_id)    → coroutine returning full response string
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.client = AsyncGroq(api_key=api_key or os.environ["GROQ_API_KEY"])
        self.model  = _CHAT_MODEL

    def _build_messages(
        self,
        user_message: str,
        history: list[dict],
        context: str,
    ) -> list[dict]:
        """
        Build the messages list for the Groq API call.

        Structure:
          [system_with_context] + [conversation_history] + [user_message]

        We inject the KB context into the system message rather than as a
        separate user turn. This keeps the conversation history clean and
        prevents the context from growing the history on every turn.
        """
        system_with_context = (
            _SYSTEM_PROMPT
            + "\n\n---\n\nCONTEXT FROM KNOWLEDGE BASE:\n\n"
            + context
            + "\n\n---\n\nUse the above context to answer the user's question. "
            "If the context doesn't cover it, answer from general knowledge."
        )

        messages = [{"role": "system", "content": system_with_context}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        return messages

    async def stream(
        self,
        message: str,
        session_id: str,
    ) -> AsyncGenerator[str, None]:
        """
        Stream a response to the user's message as SSE events.

        Each yielded string is a Server-Sent Event line, ready to be
        returned directly from a FastAPI StreamingResponse.

        Format:
          data: {"chunk": "text fragment"}\n\n
          data: [DONE]\n\n

        Usage in FastAPI:
          return StreamingResponse(
              chat_agent.stream(msg, sid),
              media_type="text/event-stream"
          )
        """
        history = _get_history(session_id)

        # Retrieve relevant KB entries — zero API cost, microseconds
        entries = retrieve(message, k=4)
        context = format_context(entries)

        logger.info(
            f"CHATBOT | [{session_id[:8]}] Query: {message[:60]}... | "
            f"KB entries retrieved: {len(entries)}"
        )

        messages = self._build_messages(message, history, context)

        full_response: list[str] = []

        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.4,   # slight warmth for conversational tone
                max_tokens=1024,   # enough for thorough answers; prevents runaway
                stream=True,
            )

            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    full_response.append(delta)
                    # Yield each chunk as an SSE event
                    yield f"data: {json.dumps({'chunk': delta})}\n\n"

            # Stream complete — save the full turn to history
            complete_response = "".join(full_response)
            _save_turn(session_id, message, complete_response)

            logger.info(
                f"CHATBOT | [{session_id[:8]}] Response: "
                f"{len(complete_response)} chars"
            )

        except Exception as exc:
            logger.error(f"CHATBOT | [{session_id[:8]}] Stream failed: {exc}")
            error_msg = (
                "I'm having trouble connecting right now. "
                "Please try again in a moment."
            )
            yield f"data: {json.dumps({'chunk': error_msg})}\n\n"

        finally:
            yield "data: [DONE]\n\n"

    async def chat(
        self,
        message: str,
        session_id: str,
    ) -> str:
        """
        Non-streaming version — returns the complete response as a string.
        Used as a fallback or for programmatic callers that don't support SSE.
        """
        history = _get_history(session_id)
        entries = retrieve(message, k=4)
        context = format_context(entries)
        messages = self._build_messages(message, history, context)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.4,
                max_tokens=1024,
            )
            reply = response.choices[0].message.content.strip()
            _save_turn(session_id, message, reply)
            return reply

        except Exception as exc:
            logger.error(f"CHATBOT | [{session_id[:8]}] Chat failed: {exc}")
            return (
                "I'm having trouble connecting right now. "
                "Please try again in a moment."
            )


# ─── Global Instance ─────────────────────────────────────────────────────────

chat_agent = ChatAgent()
