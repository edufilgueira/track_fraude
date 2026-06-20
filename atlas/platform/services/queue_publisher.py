from __future__ import annotations

from dataclasses import dataclass

from track_fraude_core.pipeline_queue import PipelineQueueMessage


@dataclass(frozen=True)
class QueuePublishResult:
    queue_name: str
    message_id: str


class QueuePublisher:
    def __init__(self, *, queue_url: str) -> None:
        self.queue_url = queue_url

    def publish(
        self,
        *,
        queue_name: str,
        message: PipelineQueueMessage,
    ) -> QueuePublishResult:
        try:
            import pika
        except ImportError as exc:
            raise RuntimeError("pika não está instalado na Platform API") from exc

        message_id = f"pipeline-{message.run_id}"
        connection = pika.BlockingConnection(pika.URLParameters(self.queue_url))
        try:
            channel = connection.channel()
            channel.queue_declare(queue=queue_name, durable=True)
            channel.basic_publish(
                exchange="",
                routing_key=queue_name,
                body=message.to_json().encode("utf-8"),
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=2,
                    message_id=message_id,
                ),
            )
        finally:
            connection.close()

        return QueuePublishResult(queue_name=queue_name, message_id=message_id)
