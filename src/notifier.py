import os
import json
import logging
from typing import Optional, List
import requests

logger = logging.getLogger(__name__)

class Notifier:
    """
    Handles outbound notifications for key trade lifecycle events.
    Supports Slack/Discord Webhooks, Telegram, and fallbacks to Console logs.
    """

    def __init__(
        self,
        notifier_type: str = None,
        webhook_url: str = None,
        telegram_token: str = None,
        telegram_chat_id: str = None
    ):
        self.notifier_type = notifier_type or os.environ.get("NOTIFIER_TYPE", "console")
        self.webhook_url = webhook_url or os.environ.get("NOTIFIER_WEBHOOK_URL")
        self.telegram_token = telegram_token or os.environ.get("NOTIFIER_TELEGRAM_TOKEN")
        self.telegram_chat_id = telegram_chat_id or os.environ.get("NOTIFIER_TELEGRAM_CHAT_ID")

    def notify(self, message: str) -> None:
        """Sends a text alert to configured notifier channels."""
        logger.info(f"[NOTIFIER]: {message}")

        if "webhook" in self.notifier_type and self.webhook_url:
            self._send_webhook(message)

        if "telegram" in self.notifier_type and self.telegram_token and self.telegram_chat_id:
            self._send_telegram(message)

    def _send_webhook(self, message: str) -> None:
        # Standard payload structure supporting Slack, Discord, and custom JSON targets
        payload = {"text": message}
        
        # If it is a Discord Webhook, they expect the "content" field
        if "discord.com" in self.webhook_url:
            payload = {"content": message}

        try:
            response = requests.post(self.webhook_url, json=payload, timeout=5)
            if response.status_code not in [200, 204]:
                logger.error(f"Webhook notification failed: {response.status_code} - {response.text}")
        except Exception as ex:
            logger.error(f"Failed to transmit webhook alert: {ex}")

    def _send_telegram(self, message: str) -> None:
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        try:
            response = requests.post(url, json=payload, timeout=5)
            if response.status_code != 200:
                logger.error(f"Telegram notification failed: {response.status_code} - {response.text}")
        except Exception as ex:
            logger.error(f"Failed to transmit Telegram alert: {ex}")
