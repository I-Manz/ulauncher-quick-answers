import json
import textwrap
import urllib.parse
import urllib.request

from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.HideWindowAction import HideWindowAction
from ulauncher.api.shared.action.CopyToClipboardAction import CopyToClipboardAction
from ulauncher.api.shared.action.ExtensionCustomAction import ExtensionCustomAction

ICON = "images/icon.png"
USER_AGENT = "Mozilla/5.0 (X11; Fedora; Linux x86_64) ulauncher-quick-answers"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def make_item(name, description="", on_enter=None):
    return ExtensionResultItem(
        icon=ICON,
        name=name,
        description=description,
        on_enter=on_enter or HideWindowAction(),
    )


def wrap(text, width):
    return "\n".join(textwrap.wrap(text, width=width)) or text


def get_width(extension):
    try:
        return max(20, int(extension.preferences.get("wrap_length")))
    except (TypeError, ValueError):
        return 64


def ddg_lookup(query):
    """Return an answer string from DuckDuckGo Instant Answer, or None."""
    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "no_html": 1,
        "skip_disambig": 1,
    })
    req = urllib.request.Request(
        "https://api.duckduckgo.com/?" + params,
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8", errors="replace").strip()
    if not raw:
        return None
    data = json.loads(raw)

    for field in ("Answer", "AbstractText", "Definition"):
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for topic in data.get("RelatedTopics", []):
        text = topic.get("Text") if isinstance(topic, dict) else None
        if text:
            return text.strip()
    return None


def ask_groq(api_key, model, system_prompt, question):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt or "Answer briefly."},
            {"role": "user", "content": question},
        ],
    }).encode()
    req = urllib.request.Request(
        GROQ_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)["choices"][0]["message"]["content"].strip()


class QuickAnswers(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryListener())
        self.subscribe(ItemEnterEvent, ItemEnterListener())


class KeywordQueryListener(EventListener):
    def on_event(self, event, extension):
        keyword = event.get_keyword()
        query = (event.get_argument() or "").strip()
        prefs = extension.preferences
        is_ai = keyword == prefs.get("ai_kw")

        if not query:
            hint = "Type your question, then press Enter" if is_ai else "Type something to look up"
            return RenderResultListAction([make_item("No question yet", hint)])

        if is_ai:
            # Nothing is sent until the user presses Enter
            item = make_item(
                "Ask AI: " + query,
                "Press Enter to send",
                ExtensionCustomAction({"q": query}, keep_app_open=True),
            )
            return RenderResultListAction([item])

        # dd keyword: instant answer, queried as you type
        try:
            answer = ddg_lookup(query)
        except Exception as e:
            return RenderResultListAction([make_item("Lookup failed", str(e))])

        if not answer:
            return RenderResultListAction([
                make_item("No instant answer", "Try rephrasing, or use the ai keyword")
            ])

        return RenderResultListAction([
            make_item(
                "DuckDuckGo",
                wrap(answer, get_width(extension)),
                CopyToClipboardAction(answer),
            )
        ])


class ItemEnterListener(EventListener):
    def on_event(self, event, extension):
        question = (event.get_data() or {}).get("q", "")
        prefs = extension.preferences
        key = (prefs.get("groq_key") or "").strip()

        if not key:
            return RenderResultListAction([
                make_item("Groq API key missing",
                          "Add it in Ulauncher preferences > Extensions")
            ])

        try:
            answer = ask_groq(
                key,
                (prefs.get("groq_model") or "").strip(),
                prefs.get("default_prompt"),
                question,
            )
        except Exception as e:
            return RenderResultListAction([make_item("An error occurred", str(e))])

        return RenderResultListAction([
            make_item(
                "AI answer (Enter to copy)",
                wrap(answer, get_width(extension)),
                CopyToClipboardAction(answer),
            )
        ])


if __name__ == "__main__":
    QuickAnswers().run()