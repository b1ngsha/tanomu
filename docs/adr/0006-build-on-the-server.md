---
status: accepted
---

# Build images on the server, behind its outbound proxy

ADR 0005 assumed the cn-shanghai server couldn't reach the internet, so images were built on the GitHub runner and streamed over SSH. Measured on the first deploy, the opposite held: runner → server SSH ran at about 15 KB/s (a 110 MB image would take two hours), while the server, through the Clash proxy already running on it (`127.0.0.1:7890`), fetched from npm at about 1.3 MB/s and GitHub at about 1 MB/s, and reached Docker Hub. So the deploy job now sends only the source (`git archive`, ~50 KB) over SSH and the server runs `docker compose build`: the Docker daemon pulls base and third-party images through the proxy (systemd drop-in), build steps reach it via `network: host` plus `HTTP(S)_PROXY` build args from the `BUILD_PROXY` variable, and the build client gets the same proxy in its environment because it fetches registry tokens itself. A trial build on the server took 135 s cold, and pulling `pgvector/pgvector` (641 MB) took under 3 minutes. The server still needs no GitHub credentials and there is still no registry. The cost is that deploys depend on the server's proxy being up (a running service is unaffected if it isn't) and builds use the server's CPU; revisit if either becomes a problem or there is more than one server.
