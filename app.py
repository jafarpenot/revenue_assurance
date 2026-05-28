"""
Gradio UI for the B2B Revenue Assurance demo.

Run:  python app.py
Then open http://localhost:7860

Drop a real KPMG logo at assets/kpmg_logo.png to replace the text fallback.
"""

import base64
import os
import queue
import re
import sys
import threading

from dotenv import load_dotenv


load_dotenv()
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ANTHROPIC_API_KEY missing — put it in .env")
if not os.path.exists("data/billing.db"):
    sys.exit("data/billing.db missing — run `python generate_data.py` first")

import gradio as gr  # noqa: E402

import agents  # noqa: E402


# -----------------------------------------------------------------------------
# Header / branding
# -----------------------------------------------------------------------------
KPMG_BLUE = "#00338D"

def _header_html() -> str:
    logo_path = "assets/kpmg_logo.png"
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = "png"  # assume png for the placeholder; jpg would still render fine via this MIME
        logo_block = f'<img src="data:image/{ext};base64,{b64}" style="height: 48px; display: block;" alt="KPMG">'
    else:
        logo_block = (
            f'<span style="font-weight: 900; font-size: 28px; letter-spacing: -1px; '
            f'color: {KPMG_BLUE}; font-family: Arial, Helvetica, sans-serif;">KPMG</span>'
        )
    return f"""
    <div style="display: flex; align-items: center; gap: 24px;
                padding: 16px 24px; border-bottom: 1px solid #e5e7eb;
                background: #ffffff;">
        <div>{logo_block}</div>
        <div style="border-left: 1px solid #e5e7eb; height: 44px;"></div>
        <div>
            <div style="font-size: 20px; font-weight: 600; color: #111827; line-height: 1.2;">
                B2B Revenue Assurance — Agentic Scan
            </div>
            <div style="font-size: 13px; color: #6b7280; margin-top: 4px;">
                April 2026 &middot; Beeline Kazakhstan &middot; Powered by Claude Sonnet 4.5
            </div>
        </div>
    </div>
    """


# -----------------------------------------------------------------------------
# Event formatting for the chat bubble
# -----------------------------------------------------------------------------
def _truncate(s: str, n: int) -> str:
    s = str(s).strip().replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


def _format_event(label: str, kind: str, content: str):
    """Turn an agent event into a single markdown line. Returns None to drop."""
    if kind == "think":
        return f"> **{label}** — {_truncate(content, 400)}"
    if kind == "call":
        # content is "tool_name {json}"
        return f"&nbsp;&nbsp;`{label}` → `{_truncate(content, 220)}`"
    if kind == "recv":
        first = content.strip().split("\n", 1)[0]
        return f"&nbsp;&nbsp;`{label}` ← {_truncate(first, 180)}"
    if kind == "info":
        return f"**{label}** · {_truncate(content, 200)}"
    return None  # drop [final] placeholders


# -----------------------------------------------------------------------------
# Routing + streaming
# -----------------------------------------------------------------------------
_SUB_RE = re.compile(r"SUB_\d+", re.IGNORECASE)
_SCAN_RE = re.compile(r"\b(full[\s-]?scan|full report|run\s+a\s+full|scan the (subscriber|base))", re.IGNORECASE)


def _route_and_run(message: str, event_cb):
    """Decide which agent to run and execute it. Returns the final text."""
    agents.set_ui_callback(event_cb)
    sub_match = _SUB_RE.search(message)
    if sub_match:
        subscriber_id = sub_match.group(0).upper()
        event_cb("ROUTER", "info", f"Dispatching to Investigator for {subscriber_id}")
        return agents.run_investigator(subscriber_id, message)
    if _SCAN_RE.search(message):
        event_cb("ROUTER", "info", "Running full Orchestrator scan (this may take several minutes)")
        return agents.run_orchestrator()
    event_cb("ROUTER", "info", "Routing to Orchestrator with your prompt as the brief")
    return agents.run_orchestrator(user_message=message)


def stream_agent_response(message, history):
    """Gradio chat generator. Yields the assistant message as it grows."""
    if not message or not message.strip():
        yield "Please enter a question or click one of the example prompts."
        return

    q: "queue.Queue" = queue.Queue()
    result_box = [None]
    error_box = [None]

    def event_cb(label, kind, content):
        q.put(("event", label, kind, content))

    def runner():
        try:
            agents.init_log("agent_trace.log")
            result_box[0] = _route_and_run(message, event_cb)
        except Exception as e:  # noqa: BLE001
            error_box[0] = e
        finally:
            agents.set_ui_callback(None)
            agents.close_log()
            q.put(None)

    threading.Thread(target=runner, daemon=True).start()

    rendered: list[str] = []
    yield "_Working…_"

    while True:
        item = q.get()
        if item is None:
            break
        if item[0] == "event":
            _, label, kind, content = item
            line = _format_event(label, kind, content)
            if line:
                rendered.append(line)
                yield "\n\n".join(rendered)

    if error_box[0] is not None:
        yield "\n\n".join(rendered) + f"\n\n**Error:** `{error_box[0]}`"
        return

    final = (result_box[0] or "").strip()
    if final:
        yield "\n\n".join(rendered) + "\n\n---\n\n" + final
    else:
        yield "\n\n".join(rendered) + "\n\n_(no final answer)_"


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
PRESET_PROMPTS = [
    "Investigate SUB_055 — CORP_001 MiningCo overage rate looks wrong",
    "Investigate SUB_058 — CORP_002 RegionalBank rate 0.18/MB looks suspiciously low",
    "Investigate SUB_060 — verify CORP_003 LogisticsKZ pooled quota is being enforced",
    "Investigate SUB_031 — Netflix CDRs charged at 0 KZT on BASIC_15 plan",
    "Run a full April 2026 revenue assurance scan",
]


with gr.Blocks(title="B2B Revenue Assurance") as demo:
    gr.HTML(_header_html())

    gr.ChatInterface(
        fn=stream_agent_response,
        examples=PRESET_PROMPTS,
        chatbot=gr.Chatbot(
            height=560,
            show_label=False,
            render_markdown=True,
        ),
        textbox=gr.Textbox(
            placeholder="Ask the agent — e.g. 'Investigate SUB_055' or 'Run a full April 2026 scan'",
            container=False,
            scale=7,
        ),
    )

    gr.HTML(
        '<div style="padding: 8px 24px; color: #9ca3af; font-size: 12px; '
        'border-top: 1px solid #e5e7eb; margin-top: 8px;">'
        'Demo MVP &middot; data is synthetic &middot; '
        'full reasoning trail written to <code>agent_trace.log</code>'
        "</div>"
    )


if __name__ == "__main__":
    server_name = os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1")
    server_port = int(os.environ.get("GRADIO_SERVER_PORT", "7860"))
    # In Docker we bind to 0.0.0.0 — don't try to auto-open a browser there.
    open_browser = server_name != "0.0.0.0"
    demo.launch(
        server_name=server_name,
        server_port=server_port,
        inbrowser=open_browser,
        share=False,
        theme=gr.themes.Soft(primary_hue="blue"),
    )
