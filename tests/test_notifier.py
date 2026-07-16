import unittest
from unittest.mock import patch, MagicMock
from src.notifier import Notifier

class TestNotifier(unittest.TestCase):
    @patch("requests.post")
    def test_webhook_slack_style(self, mock_post):
        # Set up a generic slack webhook notifier
        notifier = Notifier(
            notifier_type="webhook",
            webhook_url="https://hooks.slack.com/services/test"
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        notifier.notify("Hello Slack")

        mock_post.assert_called_once_with(
            "https://hooks.slack.com/services/test",
            json={"text": "Hello Slack"},
            timeout=5
        )

    @patch("requests.post")
    def test_webhook_discord_style(self, mock_post):
        # Discord expects the "content" field
        notifier = Notifier(
            notifier_type="webhook",
            webhook_url="https://discord.com/api/webhooks/test"
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_post.return_value = mock_response

        notifier.notify("Hello Discord")

        mock_post.assert_called_once_with(
            "https://discord.com/api/webhooks/test",
            json={"content": "Hello Discord"},
            timeout=5
        )

    @patch("requests.post")
    def test_telegram_message(self, mock_post):
        notifier = Notifier(
            notifier_type="telegram",
            telegram_token="TEST_TOKEN",
            telegram_chat_id="12345"
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        notifier.notify("Hello Telegram")

        mock_post.assert_called_once_with(
            "https://api.telegram.org/botTEST_TOKEN/sendMessage",
            json={
                "chat_id": "12345",
                "text": "Hello Telegram",
                "parse_mode": "HTML"
            },
            timeout=5
        )

if __name__ == "__main__":
    unittest.main()
