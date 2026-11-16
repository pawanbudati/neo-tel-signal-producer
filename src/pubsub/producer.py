import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from google.cloud import pubsub_v1
from google.oauth2 import service_account

from config.settings import settings
from src.logger import logger
from src.models import ParsedSignal


class PubSubSignalProducer:
    """
    Google Cloud Pub/Sub Signal Producer.
    
    Publishes parsed trading signals from Telegram extraction to a Google Cloud
    Pub/Sub topic. Decouples the Telegram listener from account-level executors.
    
    Architectural highlights:
    - Zero server management (serverless GCP infrastructure)
    - Always Free tier compliant (10 GB/month message ingestion & delivery free)
    - Native message ordering per contract key (FIFO execution guarantees)
    - Full fanout replication across all registered consumer account subscriptions
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        topic: Optional[str] = None,
        credentials_path: Optional[str] = None,
        emulator_host: Optional[str] = None,
    ):
        self.project_id = project_id or settings.gcp_project_id
        self.topic_id = topic or settings.pubsub_topic_signals
        self.credentials_path = credentials_path or settings.pubsub_credentials_path
        self.emulator_host = emulator_host or settings.pubsub_emulator_host

        if self.emulator_host:
            os.environ["PUBSUB_EMULATOR_HOST"] = self.emulator_host

        self.credentials = None
        if self.credentials_path and os.path.exists(self.credentials_path):
            self.credentials = service_account.Credentials.from_service_account_file(
                self.credentials_path
            )

        self.publisher: Optional[pubsub_v1.PublisherClient] = None
        self.topic_path: Optional[str] = None
        self._is_started = False

    async def start(self):
        """Initializes and connects the Google Cloud Pub/Sub publisher."""
        if self._is_started and self.publisher:
            return

        if not self.project_id:
            raise ValueError(
                "GCP_PROJECT_ID is not configured. Set GCP_PROJECT_ID in producer/.env "
                "or pass project_id to PubSubSignalProducer."
            )

        logger.info(
            f"[cyan]Initializing GCP Pub/Sub Signal Producer: Project='{self.project_id}', "
            f"Topic='{self.topic_id}'...[/cyan]"
        )

        # Enable message ordering per contract key for FIFO consistency
        publisher_options = pubsub_v1.types.PublisherOptions(
            enable_message_ordering=True
        )

        self.publisher = pubsub_v1.PublisherClient(
            credentials=self.credentials,
            publisher_options=publisher_options,
        )
        self.topic_path = self.publisher.topic_path(self.project_id, self.topic_id)
        self._is_started = True

        logger.info(
            f"[bold green]Pub/Sub Signal Producer ready. Target topic: '{self.topic_path}'.[/bold green]"
        )

    async def stop(self):
        """Cleans up the Pub/Sub producer."""
        if self.publisher and self._is_started:
            logger.info("[cyan]Stopping Pub/Sub Signal Producer...[/cyan]")
            self._is_started = False
            logger.info("[bold green]Pub/Sub Signal Producer stopped cleanly.[/bold green]")

    async def publish(self, signal: ParsedSignal) -> Dict[str, Any]:
        """
        Publishes a ParsedSignal to the Google Cloud Pub/Sub topic.
        Uses contract_key as ordering_key to ensure strict FIFO delivery per instrument strike.
        """
        if not self._is_started or not self.publisher or not self.topic_path:
            await self.start()

        key = signal.contract_key()
        event_id = str(uuid.uuid4())
        payload = signal.model_dump()
        payload["_meta"] = {
            "event_id": event_id,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "source": "telegram_gemini_extractor",
        }

        data_bytes = json.dumps(payload, default=str).encode("utf-8")
        attributes = {
            "event_id": event_id,
            "signal_type": signal.signal_type.value,
            "contract_key": str(key),
            "source": "telegram_gemini_extractor",
        }

        try:
            logger.info(
                f"[bold cyan]Pub/Sub Producer: Publishing signal[/bold cyan] event_id={event_id} | "
                f"OrderingKey={key} | Type={signal.signal_type.value} -> Topic='{self.topic_id}'"
            )

            # Non-blocking publish to threadpool returning a Future
            future = self.publisher.publish(
                self.topic_path,
                data=data_bytes,
                ordering_key=key,
                **attributes,
            )

            # Await the publish receipt asynchronously without blocking the event loop
            message_id = await asyncio.wrap_future(future)

            result = {
                "success": True,
                "event_id": event_id,
                "message_id": message_id,
                "topic": self.topic_id,
                "ordering_key": key,
            }
            logger.info(
                f"[bold green]Pub/Sub Producer: Published successfully[/bold green] "
                f"[message_id={message_id}, topic={self.topic_id}]"
            )
            return result

        except Exception as e:
            logger.error(
                f"[bold red]Pub/Sub Producer: Failed to publish signal to {self.topic_id}:[/bold red] {e}",
                exc_info=True,
            )
            return {"success": False, "error": str(e), "event_id": event_id}
