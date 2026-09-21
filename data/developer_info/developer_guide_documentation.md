# AuraOps Developer Documentation

Welcome to the **AuraOps Technologies** developer portal. This guide outlines how to authenticate, integrate our SDKs, use our CLI, and connect webhooks to your CI/CD pipelines.

---

## 1. Quickstart

### Prerequisites
- Node.js v18+ or Python 3.10+
- An active AuraOps API key (obtainable via `AuraOps Dashboard > Settings > Developer Tokens`)

### Installing the CLI

Install the official command-line utility:

```bash
# Via npm
npm install -g @auraops/cli

# Via Homebrew (macOS/Linux)
brew tap auraops/tap
brew install auraops-cli
```

### Authenticating the CLI

Log in using your account token:

```bash
auraops auth login --token <YOUR_PERSONAL_ACCESS_TOKEN>
```

Verify your workspace context:

```bash
auraops workspace list
```

---

## 2. API Architecture & Standards

- **Base URL:** `https://api.auraops.demo/v1`
- **Format:** JSON (`Content-Type: application/json`)
- **Authentication:** Bearer token authentication via HTTP request headers:
  ```http
  Authorization: Bearer ao_live_98f7e6d5c4b3a210
  ```
- **Rate Limits:**
  - Free Tier: 60 requests/minute
  - Team Tier: 600 requests/minute
  - Enterprise: Custom / Uncapped

---

## 3. Core REST Endpoints

### Deployments

#### Trigger a Deployment
```http
POST /v1/projects/{project_id}/deployments
```

**Payload:**
```json
{
  "environment": "production",
  "commit_sha": "7b2e5a19c",
  "strategy": "canary",
  "canary_steps": [10, 25, 50, 100],
  "auto_rollback": true
}
```

**Response (`202 Accepted`):**
```json
{
  "deployment_id": "dep_910248a",
  "status": "queued",
  "created_at": "2026-09-18T16:20:00Z"
}
```

#### Fetch Deployment Telemetry
```http
GET /v1/deployments/{deployment_id}/health
```

---

## 4. SDK Integration (Node.js & Python)

### Node.js / TypeScript

```typescript
import { AuraOpsClient } from "@auraops/sdk";

const client = new AuraOpsClient({
  apiKey: process.env.AURAOPS_API_KEY,
  environment: "production",
});

async function runDeploy() {
  const deployment = await client.deployments.create({
    projectId: "proj_edge_service",
    branch: "main",
    canarySteps: [20, 50, 100],
  });

  console.log(`Deployment launched: ${deployment.id}`);
}

runDeploy();
```

### Python

```python
import os
from auraops import Client

client = Client(api_key=os.getenv("AURAOPS_API_KEY"))

deployment = client.deployments.trigger(
    project_id="proj_edge_service",
    strategy="blue-green",
    auto_rollback=True,
)

print(f"Tracking run: {deployment.id}")
```

---

## 5. Webhook Events

Configure webhooks under **Settings > Webhooks** to receive event-driven alerts.

### Event Types
| Event Name | Description |
| :--- | :--- |
| `deployment.started` | Fired immediately when pipeline initializes |
| `deployment.canary_promoted` | Triggered when a canary tier passes threshold checks |
| `deployment.failed` | Dispatched if build or health checks fail |
| `anomaly.detected` | Observability alert triggered during a rollout |

### Verifying Signatures
All incoming webhook requests include a signature header:
```http
X-AuraOps-Signature: sha256=4f3c7e...
```
Validate this signature against your webhook secret using HMAC-SHA256 to ensure authenticity.

---

## 6. Community & Resources
- **API Reference:** `https://docs.auraops.demo/api`
- **GitHub Organization:** `https://github.com/auraops`
- **Discord Community:** `https://discord.gg/auraops-devs`