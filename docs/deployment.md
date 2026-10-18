# Deployment

tanomu runs on a single Volcano Engine cloud server under Docker Compose. Every push to `main` that passes CI builds an image, pushes it to Volcano Engine Container Registry, and redeploys over SSH (the `deploy` job in `.github/workflows/ci.yml`).

On the server everything lives in `/opt/tanomu`:

```
/opt/tanomu/
├── compose.yml   # copied from deploy/compose.yml on every deploy
├── backup.sh     # copied from deploy/backup.sh on every deploy
├── .env          # maintained by hand, except TANOMU_IMAGE (written by the deploy job)
└── backups/      # daily pg_dump files + backup.log
```

## First-time setup

### 1. Server

- Install Docker Engine with the Compose plugin.
- Create a deploy user that can run `docker` (member of the `docker` group) and owns `/opt/tanomu`:

  ```sh
  sudo mkdir -p /opt/tanomu && sudo chown deploy:deploy /opt/tanomu
  ```

- Create `/opt/tanomu/.env` with the same variables as `.env.example`, **except** `DATABASE_URL` (compose builds it), plus a `POSTGRES_PASSWORD` (hex only, since it is embedded in a connection URL: `openssl rand -hex 32`):

  ```sh
  POSTGRES_PASSWORD=<openssl rand -hex 32>
  FEISHU_APP_ID=...
  FEISHU_APP_SECRET=...
  CHAT_PROVIDER_PROTOCOL=openai
  CHAT_PROVIDER_BASE_URL=...
  CHAT_PROVIDER_API_KEY=...
  CHAT_MODEL=...
  ```

  `POSTGRES_PASSWORD` only takes effect when the database volume is first created. Changing it later requires `ALTER USER` inside Postgres as well.

### 2. Container registry

In Volcano Engine Container Registry, create an instance, a namespace, and a repository for tanomu, plus access credentials for pushing and pulling. The deploy job logs the server into the registry on every run, so these credentials are also stored in the deploy user's `~/.docker/config.json`.

### 3. SSH deploy key

Generate a dedicated key pair with no passphrase, authorize it for the deploy user, and capture the server's host key:

```sh
ssh-keygen -t ed25519 -N "" -C tanomu-deploy -f tanomu-deploy
ssh-copy-id -i tanomu-deploy.pub deploy@<server>
ssh-keyscan <server>   # value for DEPLOY_KNOWN_HOSTS
```

### 4. GitHub variables and secrets

Under the repository's Settings → Secrets and variables → Actions.

Variables (not sensitive, so the image tag stays readable in logs):

| Variable           | Value                                                     |
| ------------------ | --------------------------------------------------------- |
| `REGISTRY`         | Registry host, e.g. `<instance>-cn-beijing.cr.volces.com` |
| `IMAGE_REPOSITORY` | `<namespace>/<repository>`                                |

Secrets:

| Secret                                    | Value                                       |
| ----------------------------------------- | ------------------------------------------- |
| `REGISTRY_USERNAME` / `REGISTRY_PASSWORD` | Registry credentials                        |
| `DEPLOY_HOST` / `DEPLOY_USER`             | Server address and deploy user              |
| `DEPLOY_SSH_KEY`                          | Contents of the private key `tanomu-deploy` |
| `DEPLOY_KNOWN_HOSTS`                      | Output of `ssh-keyscan <server>`            |

### 5. One Feishu app per running instance

Feishu's long connection delivers each event to only **one** connected client. If `pnpm dev` runs locally with the production app's credentials, it randomly steals messages from production. Use a separate Feishu app for local development.

## Operations

- **Deploy**: merge to `main`. The job fails if the server doesn't log `tanomu is listening` within 60 s, and prints the last 50 log lines.
- **Roll back**: on the server, set `TANOMU_IMAGE` in `.env` to an earlier `<registry>/<repository>:<git sha>` and run `docker compose up -d`. Images older than a week are pruned on deploy; older ones can be pulled from the registry again.
- **Logs**: `docker compose logs -f server`.
- **Backups**: cron runs `backup.sh` daily at 03:30 server time and keeps 14 days (`KEEP_DAYS`). Backups stay on the server; copying them off-box is not set up yet.
- **Restore**:

  ```sh
  docker compose exec -T db pg_restore -U tanomu -d tanomu --clean --if-exists < backups/tanomu-<date>.dump
  ```
