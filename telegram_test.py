
import os
import json
import urllib.request

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"


def telegram_request(method, payload=None):
    data = None

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        f"{BASE_URL}/{method}",
        data=data,
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def main():
    updates = telegram_request("getUpdates")

    if not updates["ok"]:
        raise RuntimeError("Telegram API error")

    chats = []

    for update in updates["result"]:
        message = update.get("message", {})
        chat = message.get("chat", {})

        if chat.get("type") == "private":
            chats.append(chat["id"])

    chats = list(set(chats))

    if len(chats) != 1:
        raise RuntimeError(
            f"Expected one private chat, found {len(chats)}. "
            "Send /start to your bot and try again."
        )

    chat_id = chats[0]

    result = telegram_request(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": (
                "🏔 AI Endurance Coach\n\n"
                "Связь с GitHub установлена!\n"
                "Следующий этап — подключение тренировок Garmin."
            ),
        },
    )

    if not result["ok"]:
        raise RuntimeError("Message sending failed")

    print("Telegram test message sent successfully.")
    print("Chat ID:", chat_id)


if __name__ == "__main__":
    main()
