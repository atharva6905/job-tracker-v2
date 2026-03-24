from datetime import datetime, timedelta

from googleapiclient.discovery import build


class GmailClientInterface:
    def get_messages_since(
        self, account_id: str, since_timestamp: datetime, page_token=None
    ) -> dict:
        raise NotImplementedError

    def get_message_detail(self, message_id: str) -> dict:
        raise NotImplementedError


class RealGmailClient(GmailClientInterface):
    def __init__(self, credentials):
        self.service = build("gmail", "v1", credentials=credentials)

    def get_messages_since(
        self, account_id: str, since_timestamp: datetime, page_token=None
    ) -> dict:
        # Gmail API ``after:`` truncates epoch seconds to day-level precision
        # and is exclusive (``after:March_23`` = March 24 onwards).  Subtract
        # one day so same-day emails are never missed.  The caller's
        # gmail_message_id dedup check safely handles any re-fetched overlap.
        adjusted = since_timestamp - timedelta(days=1)
        unix_ts = int(adjusted.timestamp())
        kwargs: dict = {"userId": "me", "q": f"after:{unix_ts}"}
        if page_token:
            kwargs["pageToken"] = page_token
        return self.service.users().messages().list(**kwargs).execute()

    def get_message_detail(self, message_id: str) -> dict:
        return (
            self.service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            )
            .execute()
        )


class MockGmailClient(GmailClientInterface):
    def __init__(self, messages=None):
        self.messages = messages or []

    def get_messages_since(
        self, account_id: str, since_timestamp: datetime, page_token=None
    ) -> dict:
        return {"messages": [{"id": m["id"]} for m in self.messages]}

    def get_message_detail(self, message_id: str) -> dict:
        return next(m for m in self.messages if m["id"] == message_id)
