"""
agent.py — Agent response generator powered by Claude.
"""

import json
import logging
import pathlib
import sys
import anthropic

# Ensure config can be resolved
project_root = pathlib.Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config

logger = logging.getLogger(__name__)

def generate_response(
    user_message: str,
    context_obj: dict,
    policy_chunks: list[str],
    conversation_history: list[dict]
) -> str:
    """
    Agent response generator powered by Claude.
    Grounded in user memory (context_obj) and policy context (policy_chunks).
    """
    # Create the distinct user context block
    user_context_str = (
        "[USER CONTEXT — from Memory]\n"
        f"Preferences: {json.dumps(context_obj.get('preferences', {}), indent=2)}\n"
        f"Account State: {json.dumps(context_obj.get('account_state', {}), indent=2)}\n"
        f"Issue History: {json.dumps(context_obj.get('issue_history', []), indent=2)}\n"
        f"Transcript Excerpts: {json.dumps(context_obj.get('transcript_excerpts', []), indent=2)}"
    )

    # Create the distinct policy context block
    policy_context_str = "[POLICY CONTEXT — from RAG]\n"
    if policy_chunks:
        for idx, chunk in enumerate(policy_chunks):
            policy_context_str += f"Policy Document Chunk {idx + 1}:\n{chunk}\n\n"
    else:
        policy_context_str += "No relevant policy documents found.\n"

    # System instruction
    system_prompt = (
        "You are an intelligent customer support agent.\n"
        "You must respond to the user based on the provided USER CONTEXT (from their memory/history) "
        "and POLICY CONTEXT (from company documentation).\n\n"
        "Guidelines:\n"
        "1. Adopt the communication style and tone requested in the USER CONTEXT preferences (e.g., step-by-step instructions if specified).\n"
        "2. Ground your decisions and advice strictly in the POLICY CONTEXT. Do not make up policies.\n"
        "3. Address the user's issue directly, utilizing historical info in USER CONTEXT if they bring up past issues or references.\n"
        "4. Pay close attention to timestamps in USER CONTEXT. Note that the cache fix was pushed on June 15, 2024 (chat_user123_20240615), and the subsequent recurrence was reported on June 20, 2024. State that the fix was implemented 5 days ago (not 'yesterday').\n"
    )

    # Compile message sequence
    messages = []
    # Add conversation history
    for msg in conversation_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
        
    # Append user context, policy context, and current message to the latest user message
    combined_message_content = (
        f"{user_context_str}\n\n"
        f"{policy_context_str}\n"
        f"User Message:\n{user_message}"
    )
    messages.append({"role": "user", "content": combined_message_content})

    # Call Anthropic
    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model=config.CLAUDE_RESPONSE_MODEL,
            max_tokens=1024,
            temperature=0.3,
            system=system_prompt,
            messages=messages
        )
        return message.content[0].text.strip()
    except Exception as e:
        logger.error(f"Failed to query Claude for agent response: {e}")
        return "I apologize, but I am having trouble generating a response at the moment. Please try again shortly."

def generate_response_stream(
    user_message: str,
    context_obj: dict,
    policy_chunks: list[str],
    conversation_history: list[dict]
):
    """
    Yields agent response tokens one by one as they arrive from Claude.
    """
    user_context_str = (
        "[USER CONTEXT — from Memory]\n"
        f"Preferences: {json.dumps(context_obj.get('preferences', {}), indent=2)}\n"
        f"Account State: {json.dumps(context_obj.get('account_state', {}), indent=2)}\n"
        f"Issue History: {json.dumps(context_obj.get('issue_history', []), indent=2)}\n"
        f"Transcript Excerpts: {json.dumps(context_obj.get('transcript_excerpts', []), indent=2)}"
    )

    policy_context_str = "[POLICY CONTEXT — from RAG]\n"
    if policy_chunks:
        for idx, chunk in enumerate(policy_chunks):
            policy_context_str += f"Policy Document Chunk {idx + 1}:\n{chunk}\n\n"
    else:
        policy_context_str += "No relevant policy documents found.\n"

    system_prompt = (
        "You are an intelligent customer support agent.\n"
        "You must respond to the user based on the provided USER CONTEXT (from their memory/history) "
        "and POLICY CONTEXT (from company documentation).\n\n"
        "Guidelines:\n"
        "1. Adopt the communication style and tone requested in the USER CONTEXT preferences (e.g., step-by-step instructions if specified).\n"
        "2. Ground your decisions and advice strictly in the POLICY CONTEXT. Do not make up policies.\n"
        "3. Address the user's issue directly, utilizing historical info in USER CONTEXT if they bring up past issues or references.\n"
    )

    messages = []
    for msg in conversation_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
        
    combined_message_content = (
        f"{user_context_str}\n\n"
        f"{policy_context_str}\n"
        f"User Message:\n{user_message}"
    )
    messages.append({"role": "user", "content": combined_message_content})

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        with client.messages.stream(
            model=config.CLAUDE_RESPONSE_MODEL,
            max_tokens=1024,
            temperature=0.3,
            system=system_prompt,
            messages=messages
        ) as stream:
            for text in stream.text_stream:
                yield text
    except Exception as e:
        logger.error(f"Failed to stream response from Claude: {e}")
        yield "I apologize, but I am having trouble generating a response at the moment. Please try again shortly."
