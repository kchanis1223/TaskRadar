# TaskRadar cloud server deployment

This guide runs TaskRadar on an Ubuntu cloud VM while keeping the existing
OpenCode-based behavior. The cloud VM replaces the local PC as the always-on
computer.

Current Lightsail instance:

- Host: `3.38.169.147`
- SSH user: `ubuntu`
- OS: Ubuntu
- Region: Seoul

## Target architecture

Browser -> HTTPS domain or public IP -> Nginx -> Streamlit on `127.0.0.1:8501`
-> TaskRadar -> `opencode run`

TaskRadar should keep these settings on the server:

```env
TASKRADAR_MODE=demo
TASKRADAR_USE_OPENCODE=1
TASKRADAR_REQUIRE_OPENCODE=1
TASKRADAR_OPENCODE_MODEL=anthropic/claude-haiku-4-5
TASKRADAR_OPENCODE_TIMEOUT=180
TASKRADAR_OPENCODE_WORK_DIR=/var/lib/taskradar/opencode-work
TASKRADAR_OPENCODE_CONFIG_HOME=/home/ubuntu/.config/taskradar
TASKRADAR_ACCESS_PASSWORD=replace-with-a-strong-password
```

## 1. Connect to the instance

Use the Lightsail browser SSH button, or use your local SSH client with the
Lightsail default key:

```bash
ssh ubuntu@3.38.169.147
```

## 2. Install system packages

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip curl ca-certificates nginx
```

OpenCode can be installed with the official install script:

```bash
curl -fsSL https://opencode.ai/install | bash
```

Restart the shell or load the profile, then verify:

```bash
exec "$SHELL" -l
opencode --version
```

## 3. Clone and install TaskRadar

```bash
cd /home/ubuntu
git clone https://github.com/kchanis1223/TaskRadar.git
cd /home/ubuntu/TaskRadar
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

## 4. Configure OpenCode subscription auth

TaskRadar uses the same subscription-auth pattern as `BHOS_v2`: an isolated
OpenCode profile with the `opencode-claude-auth@latest` plugin. Do not run
`opencode providers login anthropic` for this setup.

Create the isolated OpenCode profile:

```bash
mkdir -p /home/ubuntu/.config/taskradar/opencode
cp /home/ubuntu/TaskRadar/deploy/opencode-taskradar.json \
  /home/ubuntu/.config/taskradar/opencode/opencode.json
```

Authenticate through the plugin-backed profile:

```bash
XDG_CONFIG_HOME=/home/ubuntu/.config/taskradar opencode
```

Inside OpenCode, run `/connect` and complete the Claude subscription auth flow
provided by `opencode-claude-auth`. After login, verify with the same profile:

```bash
XDG_CONFIG_HOME=/home/ubuntu/.config/taskradar \
  opencode run -m anthropic/claude-haiku-4-5 "Return only OK"
```

## 5. Configure TaskRadar environment

Create server-only environment variables:

```bash
nano /home/ubuntu/TaskRadar/.env
```

Use this template:

```env
TASKRADAR_MODE=demo
TASKRADAR_USE_OPENCODE=1
TASKRADAR_REQUIRE_OPENCODE=1
TASKRADAR_OPENCODE_COMMAND=/home/ubuntu/.local/bin/opencode
TASKRADAR_OPENCODE_MODEL=anthropic/claude-haiku-4-5
TASKRADAR_OPENCODE_TIMEOUT=180
TASKRADAR_OPENCODE_WORK_DIR=/var/lib/taskradar/opencode-work
TASKRADAR_OPENCODE_CONFIG_HOME=/home/ubuntu/.config/taskradar
TASKRADAR_ACCESS_PASSWORD=replace-with-a-strong-password
```

If `which opencode` prints a different path, use that value for
`TASKRADAR_OPENCODE_COMMAND`.

Prepare the OpenCode work directory:

```bash
mkdir -p /home/ubuntu/.config/taskradar/opencode
cp /home/ubuntu/TaskRadar/deploy/opencode-taskradar.json \
  /home/ubuntu/.config/taskradar/opencode/opencode.json
sudo mkdir -p /var/lib/taskradar/opencode-work
sudo chown -R ubuntu:ubuntu /var/lib/taskradar
chmod +x /home/ubuntu/TaskRadar/scripts/start_server.sh
```

## 6. Test manually

```bash
cd /home/ubuntu/TaskRadar
./scripts/start_server.sh --address 127.0.0.1 --port 8501
```

In another SSH session:

```bash
curl -I http://127.0.0.1:8501
```

Stop the manual server with `Ctrl+C` after the local check succeeds.

## 7. Install systemd service

```bash
sudo cp /home/ubuntu/TaskRadar/deploy/taskradar.service /etc/systemd/system/taskradar.service
sudo systemctl daemon-reload
sudo systemctl enable --now taskradar
sudo systemctl status taskradar --no-pager
```

Useful service commands:

```bash
sudo systemctl restart taskradar
sudo journalctl -u taskradar -f
```

## 8. Configure Nginx

Copy the sample config:

```bash
sudo cp /home/ubuntu/TaskRadar/deploy/nginx-taskradar.conf /etc/nginx/sites-available/taskradar
sudo ln -sf /etc/nginx/sites-available/taskradar /etc/nginx/sites-enabled/taskradar
sudo nginx -t
sudo systemctl reload nginx
```

Before a domain is connected, `server_name` may be the public IP. After a domain
is connected, replace it with the domain, for example:

```nginx
server_name taskradar.example.com;
```

## 9. Lightsail networking

In the Lightsail console, keep these ports open:

- TCP `22` from your trusted IPs if possible
- TCP `80`
- TCP `443`

Do not expose Streamlit port `8501` publicly. Streamlit should listen only on
`127.0.0.1`, and Nginx should be the public entry point.

## 10. HTTPS

After the domain DNS points to the Lightsail public IP, install a certificate:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d taskradar.example.com
```

## 11. Deploy updates

```bash
cd /home/ubuntu/TaskRadar
git pull --ff-only origin main
.venv/bin/python -m pip install -r requirements.txt
sudo systemctl restart taskradar
sudo journalctl -u taskradar -n 100 --no-pager
```

## 12. Health checks

Run these after setup and after each deployment:

```bash
systemctl is-active taskradar
curl -I http://127.0.0.1:8501
XDG_CONFIG_HOME=/home/ubuntu/.config/taskradar \
  opencode run -m anthropic/claude-haiku-4-5 "Return only OK"
```

Then open the public URL, enter `TASKRADAR_ACCESS_PASSWORD`, upload a sample
chat file, and confirm that analysis completes through OpenCode.
