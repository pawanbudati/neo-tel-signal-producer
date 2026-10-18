#!/usr/bin/env bash
set -Eeuo pipefail

CONTAINER_NAME="trading-kafka"
IMAGE="apache/kafka:4.1.2"
DATA_VOLUME="trading-kafka-data"

if ! command -v docker >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y docker.io
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y docker
  elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y docker
  else
    echo "Docker is missing and no supported package manager was found." >&2
    exit 1
  fi
fi

sudo systemctl enable --now docker

advertised_host="${KAFKA_ADVERTISED_HOST:-}"
if [[ -z "$advertised_host" ]]; then
  if command -v curl >/dev/null 2>&1; then
    advertised_host="$(curl -fsS --max-time 5 -H 'Metadata-Flavor: Google' \
      'http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/ip' || true)"
  fi
fi

if [[ ! "$advertised_host" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "Could not determine a valid Kafka advertised host. Set the KAFKA_ADVERTISED_HOST repository variable to the VM's private IP or DNS name." >&2
  exit 1
fi

if sudo docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
  state="$(sudo docker container inspect --format '{{.State.Status}}' "$CONTAINER_NAME")"
  if [[ "$state" == "running" ]]; then
    echo "Kafka container '$CONTAINER_NAME' is already running; leaving it unchanged."
  else
    echo "Starting existing Kafka container '$CONTAINER_NAME'."
    sudo docker start "$CONTAINER_NAME"
  fi
else
  echo "Creating Kafka container '$CONTAINER_NAME' using advertised host '$advertised_host'."
  sudo docker volume create "$DATA_VOLUME" >/dev/null
  sudo docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    -p 9092:9092 \
    -v "$DATA_VOLUME:/tmp/kraft-combined-logs" \
    -e KAFKA_NODE_ID=1 \
    -e KAFKA_PROCESS_ROLES=broker,controller \
    -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT \
    -e KAFKA_CONTROLLER_QUORUM_VOTERS=1@localhost:9093 \
    -e KAFKA_LISTENERS=PLAINTEXT://:9092,CONTROLLER://:9093 \
    -e "KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://$advertised_host:9092" \
    -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER \
    -e KAFKA_INTER_BROKER_LISTENER_NAME=PLAINTEXT \
    -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 \
    -e KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1 \
    -e KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1 \
    -e KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS=0 \
    -e CLUSTER_ID=4L6g3nShT-eMCtK--X86sw \
    -e KAFKA_LOG_DIRS=/tmp/kraft-combined-logs \
    "$IMAGE"
fi

for attempt in $(seq 1 60); do
  if sudo docker exec "$CONTAINER_NAME" /opt/kafka/bin/kafka-topics.sh \
    --bootstrap-server localhost:9092 --list >/dev/null 2>&1; then
    echo "Kafka is ready in container '$CONTAINER_NAME'."
    exit 0
  fi
  sleep 2
done

echo "Kafka did not become ready within 120 seconds. Recent container logs:" >&2
sudo docker logs --tail 100 "$CONTAINER_NAME" >&2 || true
exit 1
