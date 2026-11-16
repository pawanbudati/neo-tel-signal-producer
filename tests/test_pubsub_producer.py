import asyncio
import json
from unittest.mock import MagicMock, patch
import pytest

from src.models import ParsedSignal, SignalType, OrderCondition
from src.pubsub.producer import PubSubSignalProducer


def test_producer_init():
    producer = PubSubSignalProducer(
        project_id="test-project",
        topic="test-topic",
    )
    assert producer.project_id == "test-project"
    assert producer.topic_id == "test-topic"
    assert producer._is_started is False


@pytest.mark.asyncio
async def test_producer_missing_project_raises():
    producer = PubSubSignalProducer(project_id="", topic="test-topic")
    with pytest.raises(ValueError, match="GCP_PROJECT_ID is not configured"):
        await producer.start()


@pytest.mark.asyncio
async def test_producer_publish_success():
    producer = PubSubSignalProducer(
        project_id="test-project",
        topic="kotak_trading_signals",
    )

    mock_future = asyncio.get_running_loop().create_future()
    mock_future.set_result("mock-msg-12345")

    mock_publisher = MagicMock()
    mock_publisher.topic_path.return_value = "projects/test-project/topics/kotak_trading_signals"
    mock_publisher.publish.return_value = mock_future

    with patch("google.cloud.pubsub_v1.PublisherClient", return_value=mock_publisher):
        await producer.start()

        signal = ParsedSignal(
            is_trading_signal=True,
            signal_type=SignalType.NEW_ORDER,
            action="BUY",
            index="NIFTY",
            strike_price=24000,
            option_type="CE",
            order_condition=OrderCondition.ABOVE,
            entry_price=100.0,
            trigger_price=100.0,
            stop_loss=80.0,
            target=120.0,
            targets=[120.0, 140.0],
            reasoning="Test breakout",
            raw_message="NIFTY 24000 CE ABV 100",
        )

        result = await producer.publish(signal)

        assert result["success"] is True
        assert result["message_id"] == "mock-msg-12345"
        assert result["topic"] == "kotak_trading_signals"
        assert result["ordering_key"] == "NIFTY_24000_CE"

        mock_publisher.publish.assert_called_once()
        call_kwargs = mock_publisher.publish.call_args[1]
        call_args = mock_publisher.publish.call_args[0]

        assert call_args[0] == "projects/test-project/topics/kotak_trading_signals"
        assert call_kwargs["ordering_key"] == "NIFTY_24000_CE"
        assert call_kwargs["signal_type"] == "NEW_ORDER"

        payload = json.loads(call_kwargs["data"].decode("utf-8"))
        assert payload["strike_price"] == 24000
        assert payload["_meta"]["source"] == "telegram_gemini_extractor"


@pytest.mark.asyncio
async def test_producer_publish_failure():
    producer = PubSubSignalProducer(
        project_id="test-project",
        topic="kotak_trading_signals",
    )

    mock_publisher = MagicMock()
    mock_publisher.topic_path.return_value = "projects/test-project/topics/kotak_trading_signals"
    mock_publisher.publish.side_effect = RuntimeError("Pub/Sub connection refused")

    with patch("google.cloud.pubsub_v1.PublisherClient", return_value=mock_publisher):
        await producer.start()

        signal = ParsedSignal(
            is_trading_signal=True,
            signal_type=SignalType.CLOSE_POSITION,
            action="SELL",
            index="BANKNIFTY",
            strike_price=52000,
            option_type="PE",
            reasoning="Emergency exit",
            raw_message="Exit Banknifty",
        )

        result = await producer.publish(signal)
        assert result["success"] is False
        assert "Pub/Sub connection refused" in result["error"]
