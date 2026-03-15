# Billingonaire SDLC Specification

Version: 1.0
Owner: Engineering Team
Applies to: Backend, Frontend, Infrastructure, CI/CD, Verification, Rollback

## 1. Purpose

This specification defines the end-to-end SDLC workflow for Billingonaire, including:
- Planning and change management
- Development quality controls
- CI validation gates
- CD deployment controls
- Production verification checks
- Rollback and incident response

This document is the authoritative workflow standard for repository changes and production releases.

## 2. Scope

In scope:
- Backend service at billingonaire_backend
- Frontend app at billingonaire-ui
- GitHub workflows under .github/workflows
- Deployment scripts under firebase
- Firecrawl extraction integration
- Optional Ollama fallback using dedicated GKE or Cloud Run

Out of scope:
- Non-production sandbox prototypes
- Personal local scripts outside repository workflow

## 3. Environments

Defined environments:
- Local Development
- CI Validation
- Production

Deployment targets:
- Backend: Cloud Run
- Frontend: Firebase Hosting
- Optional LLM service:
  - Preferred: Dedicated GKE Ollama service
  - Alternate: Cloud Run Ollama service

## 4. Branch and Release Strategy

Branches:
- main: production branch
- develop: integration branch
- feature/*: short-lived feature branches
- hotfix/*: emergency fixes

Rules:
- All production changes flow through Pull Requests.
- Direct commits to main are disallowed.
- PRs require green CI and reviewer approval.
- Production deploys are triggered from main or manual workflow dispatch.

Release versioning:
- Automated release tagging via GitHub Release in CD.
- Release notes generated from commits since previous release.

## 5. SDLC Workflow Phases

### Phase A: Plan

Required artifacts before coding:
- Problem statement
- Scope and constraints
- Risk classification
- Verification plan
- Rollback plan

Acceptance criteria:
- Functional criteria documented
- Non-functional criteria documented
- Deployment impact identified

### Phase B: Build

Development standards:
- Follow existing project style and module boundaries.
- Keep deterministic extraction as primary path.
- Keep LLM fallback optional and confidence-gated.
- Do not hardcode secrets.

Code quality requirements:
- Backend formatting and lint checks
- Frontend lint checks
- Unit and integration tests for changed behavior

### Phase C: Verify in CI

CI workflow source:
- .github/workflows/ci.yml

Mandatory CI gates:
- Backend lint
- Backend unit tests with coverage output
- Frontend lint
- Frontend unit tests
- Security scan (high severity threshold)

PR merge eligibility:
- All required CI jobs pass.
- No unresolved review comments.
- No critical vulnerability introduced.

### Phase D: Deploy

CD workflow source:
- .github/workflows/cd.yml

Deployment scripts:
- firebase/backend-cloudrun-deploy.sh
- firebase/deploy-all.sh
- firebase/setup-secrets.sh
- firebase/ollama-gke-deploy.sh
- firebase/ollama-cloudrun-deploy.sh

Deployment policy:
- Deploy backend and frontend only after CI pass.
- Use service account based authentication.
- Use Secret Manager for sensitive keys.
- Use environment variables for operational controls.

LLM deployment policy:
- Preferred production LLM target is dedicated GKE Ollama.
- Cloud Run Ollama may be used for low-volume or temporary usage.
- Backend must resolve OLLAMA_BASE_URL from explicit env or discovered deployment URL.

### Phase E: Post-Deploy Verification

Required backend checks:
- Backend health endpoint responds: GET /
- Core endpoint smoke test: court order extraction path returns valid payload shape
- Firecrawl key availability validated at runtime

Required frontend checks:
- Frontend URL responds with successful HTTP status
- Basic navigation renders without runtime failure

Required LLM checks when enabled:
- Ollama health endpoint responds: GET /api/tags
- Fallback trigger path validated on low-confidence sample
- Analyzer metadata persisted with fallback diagnostics

Verification evidence:
- Capture deployment URLs
- Capture health check outcomes
- Record workflow run URL and commit SHA

### Phase F: Operate and Improve

Operational controls:
- Observe extraction quality and fallback rates
- Track deployment duration and failure causes
- Track post-deploy incidents and MTTR

Continuous improvement loop:
- Weekly review of fallback metrics
- Monthly threshold tuning for fallback triggers
- Quarterly dependency and security baseline review

## 6. Secrets and Configuration Management

Secret storage requirements:
- Production secrets must be in Google Secret Manager.
- Local development secrets may use local .env files.
- .env files must remain gitignored.

Required secrets:
- GCLOUD_SERVICE_ACCOUNT_KEY
- FIRECRAWL_API_KEY

Config controls for LLM fallback:
- ORDER_ENABLE_LLM_FALLBACK
- ORDER_LLM_PROVIDER
- ORDER_LLM_MODEL
- OLLAMA_BASE_URL
- ORDER_LLM_TIMEOUT_SECONDS
- ORDER_LLM_FALLBACK_MIN_QUALITY
- ORDER_LLM_FALLBACK_MIN_CATEGORY_CONFIDENCE
- ORDER_LLM_FALLBACK_MIN_CASES

## 7. Deployment Verification Checklist

A release is complete only when all items pass:
- CI pipeline passed for commit
- Backend deployed successfully
- Frontend deployed successfully
- Backend health check passed
- Frontend health check passed
- LLM health check passed when fallback enabled
- Smoke test for order processing passed
- Release created with commit traceability

## 8. Rollback Policy

Rollback triggers:
- Failed health checks after deploy
- Increased error rate above acceptable threshold
- Data correctness regression
- Production blocking user impact

Rollback approach:
- Backend: redeploy previous known-good image tag on Cloud Run
- Frontend: redeploy previous build on Firebase Hosting
- LLM service: switch OLLAMA_BASE_URL to known-good service endpoint or disable fallback

Rollback verification:
- Re-run backend and frontend health checks
- Re-run critical smoke tests
- Confirm incident impact resolved

## 9. Incident and Change Control

Incident response requirements:
- Incident owner assigned
- Impact summary documented
- Timeline recorded
- Root cause and corrective action documented

Change traceability requirements:
- PR link
- Workflow run link
- Deployment script path used
- Release tag and commit SHA

## 10. Ownership

Engineering responsibilities:
- Maintain CI/CD workflow health
- Maintain deployment scripts and verification checks
- Maintain extraction quality thresholds

Review responsibilities:
- Verify SDLC gates were followed
- Verify test coverage for changed paths
- Verify deployment and rollback readiness

## 11. Definition of Done

A change is done only when:
- Implementation is complete and reviewed
- Tests are added or updated and pass
- CI and CD requirements are satisfied
- Deployment verification evidence is recorded
- Operational risk is acceptable
- Rollback path is confirmed

## 12. Implementation References

Primary workflow files:
- .github/workflows/ci.yml
- .github/workflows/cd.yml

Primary deployment scripts:
- firebase/setup-secrets.sh
- firebase/backend-cloudrun-deploy.sh
- firebase/deploy-all.sh
- firebase/ollama-gke-deploy.sh
- firebase/ollama-cloudrun-deploy.sh
