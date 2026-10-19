# Deployment

tanomu runs on a single Volcano Engine cloud server (cn-shanghai) under Docker Compose. Every push to `main` that passes CI builds the image on the GitHub runner, streams it to the server over SSH (`docker save | docker load`), and restarts the service (the `deploy` job in `.github/workflows/ci.yml`). There is no container registry, and the server never pulls from the internet: Docker Hub isn't reachable from mainland China, so third-party images such as `pgvector/pgvector` are shipped the same way the first time they're needed (ADR 0005).

On the server everything lives in `/opt/tanomu`:

```
/opt/tanomu/
├── compose.yml   # copied from deploy/compose.yml on every deploy
├── backup.sh     # copied from deploy/backup.sh on every deploy
├── .env          # written by the deploy job on every deploy (mode 600); don't edit
└── backups/      # daily pg_dump files + backup.log
```

## First-time setup

### 1. Server

As root on the server (Ubuntu 22.04). Docker comes from Ubuntu's own packages, which resolve through Volcano Engine's internal mirror; `get.docker.com` is not reachable.

```sh
apt update
apt install -y docker.io docker-compose-v2
systemctl enable --now docker

adduser --disabled-password --gecos "" deploy   # key-only login
usermod -aG docker deploy                       # docker group is root-equivalent: guard the key
mkdir -p /opt/tanomu && chown deploy:deploy /opt/tanomu
```

The server needs nothing else: all configuration lives in GitHub and is written to `/opt/tanomu/.env` on every deploy.

### 2. SSH deploy key

On your machine, generate a dedicated key pair with no passphrase:

```sh
ssh-keygen -t ed25519 -N "" -C tanomu-deploy -f tanomu-deploy
cat tanomu-deploy.pub
```

On the server, as root, authorize the public key for `deploy` (it has no password, so `ssh-copy-id` won't work):

```sh
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
echo '<contents of tanomu-deploy.pub>' > /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys && chmod 600 /home/deploy/.ssh/authorized_keys
```

Back on your machine, check access and capture the host key:

```sh
ssh -i tanomu-deploy deploy@<server> docker ps
ssh-keyscan <server>   # value for DEPLOY_KNOWN_HOSTS
```

The server's security group must allow inbound SSH from anywhere: GitHub-hosted runners have no fixed IPs. Keep password login disabled.

### 3. GitHub `production` environment

Create an environment named `production` under the repository's Settings → Environments, and put everything below in it (not at repository level), so only the deploy job can read it.

Variables (not sensitive, readable in logs):

| Variable                 | Value                                                                               |
| ------------------------ | ----------------------------------------------------------------------------------- |
| `CHAT_PROVIDER_PROTOCOL` | `openai`, `anthropic`, or `google`                                                  |
| `CHAT_MODEL`             | Chat model id                                                                       |
| `DEPLOY_USER`            | `deploy` (a variable, not a secret: a secret would mask every "deploy" in the logs) |

Secrets:

| Secret                                             | Value                                                                                                                                                                 |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DEPLOY_HOST`                                      | Server address                                                                                                                                                        |
| `DEPLOY_SSH_KEY`                                   | The private key `tanomu-deploy`, set from the file: `gh secret set DEPLOY_SSH_KEY --env production < tanomu-deploy` (pasting interactively keeps only the first line) |
| `DEPLOY_KNOWN_HOSTS`                               | Output of `ssh-keyscan <server>`                                                                                                                                      |
| `POSTGRES_PASSWORD`                                | `openssl rand -hex 32` (hex only, since it is embedded in a connection URL)                                                                                           |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET`              | Credentials of the **production** Feishu app                                                                                                                          |
| `CHAT_PROVIDER_BASE_URL` / `CHAT_PROVIDER_API_KEY` | Chat model Provider                                                                                                                                                   |

GitHub secrets can't be read back. Keep a copy of `POSTGRES_PASSWORD` in a password manager: it only takes effect when the database volume is first created, and losing it locks you out of the database (changing it later also requires `ALTER USER` inside Postgres).

Adding a new app variable means adding it to this environment **and** to the `app_vars` list and `env:` block of the deploy step. A variable missing from the environment fails the deploy before anything is written to the server.

### 4. Local development shares the production Feishu app

Local `pnpm dev` and production use the same Feishu app. Feishu's long connection delivers each event to only **one** connected client, so while both run, messages are split between them at random. Stop production before debugging locally, and start it again afterwards:

```sh
docker compose stop server    # on the server, in /opt/tanomu
docker compose start server
```

## Operations

- **Deploy**: merge to `main`. The job fails if the server doesn't log `tanomu is listening` within 60 s, and prints the last 50 log lines.
- **Change config or rotate a secret**: update the `production` environment, then re-run the latest deploy job on `main`.
- **Roll back**: re-run the deploy job of an earlier successful run on `main` (it rebuilds and ships that commit's image). For a quick fix, images from the last week are still on the server: set `TANOMU_IMAGE` in `.env` to `tanomu-server:<git sha>` and run `docker compose up -d`; the next deploy overwrites it.
- **Upgrade Postgres or add a third-party image**: change the image in `deploy/compose.yml`; the next deploy ships it if the server doesn't have it.
- **Logs**: `docker compose logs -f server`.
- **Backups**: cron runs `backup.sh` daily at 03:30 server time and keeps 14 days (`KEEP_DAYS`). Backups stay on the server; copying them off-box is not set up yet.
- **Restore**:

  ```sh
  docker compose exec -T db pg_restore -U tanomu -d tanomu --clean --if-exists < backups/tanomu-<date>.dump
  ```
