from __future__ import annotations

from dataclasses import dataclass

from track_fraude_core.pipeline_queue import PipelineQueueMessage


@dataclass(frozen=True)
class QueuePublishResult:
    queue_name: str
    message_id: str


class PipelineQueuePublisher:
    def __init__(self, *, queue_url: str, queue_name: str) -> None:
        self.queue_url = queue_url
        self.queue_name = queue_name

    def publish(self, message: PipelineQueueMessage) -> QueuePublishResult:
        try:
            import pika
        except ImportError as exc:
            raise RuntimeError(
                "pika não está instalado; instale server/requirements.txt para usar pipeline.mode=queue"
            ) from exc

        params = pika.URLParameters(self.queue_url)
        message_id = f"pipeline-{message.run_id}"
        connection = pika.BlockingConnection(params)
        try:
            channel = connection.channel()
            channel.queue_declare(queue=self.queue_name, durable=True)
            channel.basic_publish(
                exchange="",
                routing_key=self.queue_name,
                body=message.to_json().encode("utf-8"),
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=2,
                    message_id=message_id,
                ),
            )
        finally:
            connection.close()

        return QueuePublishResult(queue_name=self.queue_name, message_id=message_id)
