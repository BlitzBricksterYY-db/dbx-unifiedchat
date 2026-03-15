"""
Multi-Agent Genie Chat — Databricks App (Gradio)

A streaming chat interface that connects to the multi-agent genie
Model Serving endpoint. Supports multi-turn conversations with
thread-based context, user identity forwarding, and real-time
streaming of agent thinking steps.

Deployed as a Databricks App via CLI or Asset Bundles.
"""

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Generator

import gradio as gr
import requests
from databricks.sdk.core import Config

# ---------------------------------------------------------------------------
# Local debug — load .env from project root when running outside Databricks
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"
if _ENV_FILE.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_FILE, override=False)
    except ImportError:
        pass

DEBUG = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# Configuration — resolved from app.yaml valueFrom references
# ---------------------------------------------------------------------------
SERVING_ENDPOINT_NAME = os.getenv(
    "SERVING_ENDPOINT_NAME", "multi-agent-genie-endpoint"
)

cfg = Config()
BASE_URL = f"https://{cfg.host}"
INVOCATION_URL = (
    f"{BASE_URL}/serving-endpoints/{SERVING_ENDPOINT_NAME}/invocations"
)


# ---------------------------------------------------------------------------
# Streaming helper — calls the endpoint with SSE streaming
# ---------------------------------------------------------------------------

def _build_payload(
    message: str,
    thread_id: str,
    user_id: str | None = None,
) -> dict:
    """Construct the Model Serving invocation payload."""
    payload: dict = {
        "messages": [{"role": "user", "content": message}],
    }
    context: dict = {"conversation_id": thread_id}
    if user_id:
        context["user_id"] = user_id
    payload["context"] = context
    return payload


def _stream_response(
    message: str,
    thread_id: str,
    user_id: str | None = None,
) -> Generator[str, None, None]:
    """
    Stream agent response from the Model Serving endpoint.

    Yields partial text as it arrives. Falls back to non-streaming
    if the endpoint does not support SSE.
    """
    headers = {**cfg.authenticate(), "Content-Type": "application/json"}
    payload = _build_payload(message, thread_id, user_id)

    try:
        resp = requests.post(
            INVOCATION_URL,
            headers=headers,
            json=payload,
            stream=True,
            timeout=300,
        )
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")

        if "text/event-stream" in content_type:
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[len("data:"):].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = (
                        chunk.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content", "")
                    )
                    if delta:
                        yield delta
                except json.JSONDecodeError:
                    continue
        else:
            body = resp.json()

            # Responses API format (output list)
            if "output" in body:
                for item in body["output"]:
                    text = ""
                    if isinstance(item, dict):
                        text = item.get("text", "") or item.get("content", "")
                    elif isinstance(item, str):
                        text = item
                    if text:
                        yield text + "\n"
                return

            # Chat completions format
            choices = body.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                yield msg.get("content", str(body))
            else:
                yield str(body)

    except requests.exceptions.HTTPError as exc:
        yield f"\n**Error**: {exc.response.status_code} — {exc.response.text[:500]}"
    except requests.exceptions.ConnectionError:
        yield "\n**Error**: Cannot reach the serving endpoint. Is it running?"
    except Exception as exc:
        yield f"\n**Error**: {exc}"


# ---------------------------------------------------------------------------
# Conversation state
# ---------------------------------------------------------------------------

def _new_thread_id() -> str:
    return f"app-{uuid.uuid4()}"


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------

TITLE = "Multi-Agent Genie"
DESCRIPTION = (
    "Ask questions about your data across multiple Genie spaces. "
    "The multi-agent system will plan, query, and summarise results for you."
)

CSS = """
.agent-step {
    color: #6c757d;
    font-size: 0.85em;
    border-left: 3px solid #dee2e6;
    padding-left: 8px;
    margin: 4px 0;
}
footer {visibility: hidden}
"""

EXAMPLES = [
    "Show me an overview of all available data spaces",
    "How many patients are in the database?",
    "What are the most common diagnoses?",
    "Compare medication usage across age groups",
]


def _extract_user_from_headers(request: gr.Request) -> str | None:
    """Pull the Databricks user identity from forwarded headers."""
    if request is None:
        return None
    email = request.headers.get("x-forwarded-email")
    if email:
        return email
    token = request.headers.get("x-forwarded-access-token")
    if token:
        return f"token-user-{hash(token) % 10000}"
    return None


_STEP_PATTERN = re.compile(r"^(🔹|🔀|🔍|📋|🔧|📝|⚡|✅|❓|🎯|🚀|💭|🤖|🛠️|⏭️|📍|📊|📄|ℹ️)")


def _is_agent_step(text: str) -> bool:
    """Return True if text is an internal agent step indicator."""
    return bool(_STEP_PATTERN.match(text.strip()))


def _format_step(text: str) -> str:
    """Wrap agent step text in a collapsible detail block."""
    return f"<details class='agent-step'><summary>{text.strip()}</summary></details>"


def chat_handler(
    message: str,
    history: list[dict],
    request: gr.Request,
    thread_state: str | None = None,
) -> Generator[list[dict], None, None]:
    """
    Gradio chat handler — streams agent responses back to the UI.

    Uses `type="messages"` format (list of dicts with role/content).
    """
    if not message.strip():
        yield history
        return

    thread_id = thread_state or _new_thread_id()
    user_id = _extract_user_from_headers(request)

    history = history + [{"role": "user", "content": message}]
    yield history

    accumulated = ""
    steps: list[str] = []

    for chunk in _stream_response(message, thread_id, user_id):
        if _is_agent_step(chunk):
            steps.append(_format_step(chunk))
            continue
        accumulated += chunk

        display = accumulated
        if steps:
            step_block = "\n".join(steps)
            display = (
                f"<details open><summary><b>Agent steps</b></summary>\n\n"
                f"{step_block}\n</details>\n\n{accumulated}"
            )

        yield history + [{"role": "assistant", "content": display}]

    if not accumulated and steps:
        display = "\n".join(s.replace("<details class='agent-step'>", "").replace("</details>", "").replace("<summary>", "").replace("</summary>", "") for s in steps)
        yield history + [{"role": "assistant", "content": display}]
    elif not accumulated and not steps:
        yield history + [
            {"role": "assistant", "content": "_No response from agent._"}
        ]


def build_app() -> gr.Blocks:
    """Construct the Gradio Blocks app."""
    with gr.Blocks(title=TITLE) as demo:
        gr.Markdown(f"# {TITLE}\n{DESCRIPTION}")

        thread_state = gr.State(_new_thread_id)

        chatbot = gr.Chatbot(
            label="Conversation",
            height=560,
            render_markdown=True,
            avatar_images=(None, "https://docs.databricks.com/en/_static/images/icons/databricks-genie-icon.svg"),
        )
        msg = gr.Textbox(
            placeholder="Ask a question about your data…",
            show_label=False,
            container=False,
            scale=7,
        )

        with gr.Row():
            submit_btn = gr.Button("Send", variant="primary", scale=1)
            clear_btn = gr.Button("New conversation", scale=1)

        gr.Examples(examples=EXAMPLES, inputs=msg)

        with gr.Accordion("Settings", open=False):
            endpoint_display = gr.Textbox(
                value=SERVING_ENDPOINT_NAME,
                label="Serving Endpoint",
                interactive=False,
            )
            thread_display = gr.Textbox(
                label="Thread ID",
                interactive=False,
            )

        def on_submit(message, history, request: gr.Request, thread_id):
            gen = chat_handler(message, history, request, thread_id)
            for h in gen:
                yield h, thread_id

        submit_btn.click(
            on_submit,
            inputs=[msg, chatbot, thread_state],
            outputs=[chatbot, thread_display],
        ).then(lambda: "", outputs=[msg])

        msg.submit(
            on_submit,
            inputs=[msg, chatbot, thread_state],
            outputs=[chatbot, thread_display],
        ).then(lambda: "", outputs=[msg])

        def on_clear():
            new_tid = _new_thread_id()
            return [], new_tid, new_tid

        clear_btn.click(
            on_clear,
            outputs=[chatbot, thread_state, thread_display],
        )

    return demo


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    debug = DEBUG or "--debug" in sys.argv
    port = int(os.environ.get("DATABRICKS_APP_PORT", 8000))

    if debug:
        print(f"[DEBUG] Endpoint : {SERVING_ENDPOINT_NAME}")
        print(f"[DEBUG] Host     : {cfg.host}")
        print(f"[DEBUG] URL      : {INVOCATION_URL}")
        print(f"[DEBUG] Port     : {port}")

    app = build_app()
    app.launch(
        server_name="0.0.0.0",
        server_port=port,
        debug=debug,
        show_error=debug,
        theme=gr.themes.Soft(primary_hue="blue"),
        css=CSS,
    )
else:
    app = build_app()
    port = int(os.environ.get("DATABRICKS_APP_PORT", 8000))
    app.launch(
        server_name="0.0.0.0",
        server_port=port,
        theme=gr.themes.Soft(primary_hue="blue"),
        css=CSS,
    )
