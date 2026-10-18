# GitHub Actions deployment to GCP

The `Deploy producer` workflow deploys every push to `main` and can also be started manually from the GitHub Actions tab. It syncs this repository to the VM, ensures the Kafka container is running, installs Python requirements, and restarts the `neo-tel-signal-producer` systemd service.

## Configure GitHub

In this repository's **Settings → Secrets and variables → Actions**, add:

**Secrets**

- `GCP_VM_SSH_KEY`: private SSH key for a VM account that can write to the deployment directory and run the required `sudo` systemd/install commands without a password.
- `GCP_VM_KNOWN_HOSTS`: the VM's verified SSH host key line(s), obtained and fingerprint-checked out of band.

**Variables**

- `GCP_VM_USER`: Linux account matching the public key installed on the VM.
- `GCP_VM_SSH_PORT`: optional; defaults to `22`.
- `PRODUCER_DEPLOY_PATH`: optional; defaults to `/home/<GCP_VM_USER>/apps/neo-tel-signal-producer`.
- `KAFKA_ADVERTISED_HOST`: optional; defaults to the producer VM's GCP private IP, read from its metadata server. Set this to a reachable private IP or DNS name if needed.

`GCP_VM_HOST` and `GCP_VM_USER` can each be stored as either a secret or a variable; the workflow checks both.

The VM needs Python 3, `curl`, and `sudo` access. If `rsync` or Docker is missing, the workflow attempts to install it using the VM's `apt-get`, `dnf`, or `yum` package manager. Restrict SSH ingress to trusted sources where practical. The workflow does not transfer local secrets or generated state.

## Prepare the VM once

Create the deployment directory and configure the app before enabling automatic deploys:

```bash
mkdir -p "$HOME/apps/neo-tel-signal-producer"
```

Create `producer/.env` on the VM using `.env.example` as a reference. Perform the Telethon login once on the VM so the configured session file exists in the deployment directory. Keep both files private and outside Git. The deploy account needs passwordless sudo for package installation, Docker, `install`, and the `systemctl` commands used by the services.

The Kafka container is named `trading-kafka`, uses `apache/kafka:4.1.2`, stores data in the Docker volume `trading-kafka-data`, and restarts with Docker after VM reboots. If a container with that name already exists, the workflow starts it if stopped and leaves its existing configuration intact if running. A new container advertises the producer VM's private IP on port `9092`.

Set the consumer VM's local `KAFKA_BOOTSTRAP_SERVERS` value to `<producer-private-ip>:9092`. In GCP's VPC firewall, allow TCP port `9092` only from the consumer VM or its narrow private subnet. Kafka uses plaintext here; do not expose the broker to the public internet. The producer can use `localhost:9092` as its bootstrap address.

After the first workflow run, inspect logs with:

```bash
sudo journalctl -u neo-tel-signal-producer -f
```

Kafka container logs are available with `sudo docker logs -f trading-kafka`.

Protect `main` if deployments should happen only after review. A failed deployment leaves the workflow red; review the job output and VM service logs before retrying.
