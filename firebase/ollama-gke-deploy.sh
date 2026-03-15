#!/bin/bash

# Deploy Ollama to a dedicated GKE cluster and expose it via LoadBalancer.
# Usage:
#   export GCLOUD_SERVICE_ACCOUNT_KEY='{"type":"service_account",...}'
#   export OLLAMA_MODEL='llama3.1:8b'   # optional
#   ./firebase/ollama-gke-deploy.sh

set -e

PROJECT_ID="${PROJECT_ID:-billingonaire}"
REGION="${REGION:-asia-south1}"
ZONE="${ZONE:-asia-south1-a}"
CLUSTER_NAME="${OLLAMA_GKE_CLUSTER_NAME:-billingonaire-ollama-gke}"
NAMESPACE="${OLLAMA_GKE_NAMESPACE:-ollama}"
APP_NAME="${OLLAMA_GKE_APP_NAME:-ollama}"
MODEL_NAME="${OLLAMA_MODEL:-llama3.1:8b}"
PVC_SIZE="${OLLAMA_GKE_PVC_SIZE:-50Gi}"

if [ -z "$GCLOUD_SERVICE_ACCOUNT_KEY" ]; then
  echo "❌ Error: GCLOUD_SERVICE_ACCOUNT_KEY environment variable not set"
  echo "Please set it with your service account JSON key"
  exit 1
fi

echo "🔐 Authenticating with Google Cloud..."
echo "$GCLOUD_SERVICE_ACCOUNT_KEY" > /tmp/gcloud-key.json
gcloud auth activate-service-account --key-file=/tmp/gcloud-key.json
gcloud config set project "$PROJECT_ID"

echo "📡 Enabling Kubernetes APIs..."
gcloud services enable container.googleapis.com

if ! gcloud container clusters describe "$CLUSTER_NAME" --zone "$ZONE" >/dev/null 2>&1; then
  echo "🚀 Creating GKE cluster: $CLUSTER_NAME"
  gcloud container clusters create "$CLUSTER_NAME" \
    --zone "$ZONE" \
    --num-nodes=1 \
    --machine-type=e2-standard-4 \
    --release-channel=regular
else
  echo "✅ GKE cluster already exists: $CLUSTER_NAME"
fi

echo "🔗 Fetching cluster credentials..."
gcloud container clusters get-credentials "$CLUSTER_NAME" --zone "$ZONE"

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

cat <<EOF | kubectl apply -n "$NAMESPACE" -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${APP_NAME}-data
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: ${PVC_SIZE}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${APP_NAME}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ${APP_NAME}
  template:
    metadata:
      labels:
        app: ${APP_NAME}
    spec:
      containers:
        - name: ${APP_NAME}
          image: ollama/ollama:latest
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 11434
          env:
            - name: OLLAMA_MODEL
              value: "${MODEL_NAME}"
          command:
            - /bin/sh
            - -c
            - |
              ollama serve &
              for i in \\$(seq 1 40); do
                if curl -sSf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
                  break
                fi
                sleep 2
              done
              ollama pull "${MODEL_NAME}" || true
              wait
          resources:
            requests:
              cpu: "2000m"
              memory: "4Gi"
            limits:
              cpu: "4000m"
              memory: "8Gi"
          livenessProbe:
            httpGet:
              path: /api/tags
              port: 11434
            initialDelaySeconds: 30
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /api/tags
              port: 11434
            initialDelaySeconds: 15
            periodSeconds: 15
          volumeMounts:
            - name: ollama-data
              mountPath: /root/.ollama
      volumes:
        - name: ollama-data
          persistentVolumeClaim:
            claimName: ${APP_NAME}-data
---
apiVersion: v1
kind: Service
metadata:
  name: ${APP_NAME}
spec:
  type: LoadBalancer
  selector:
    app: ${APP_NAME}
  ports:
    - name: http
      port: 11434
      targetPort: 11434
EOF

echo "⏳ Waiting for external IP..."
OLLAMA_IP=""
for i in $(seq 1 60); do
  OLLAMA_IP=$(kubectl get svc "$APP_NAME" -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)
  if [ -n "$OLLAMA_IP" ]; then
    break
  fi
  sleep 5
done

if [ -z "$OLLAMA_IP" ]; then
  echo "❌ Timed out waiting for Ollama service external IP"
  rm -f /tmp/gcloud-key.json
  exit 1
fi

OLLAMA_URL="http://${OLLAMA_IP}:11434"
echo "🌐 Ollama URL: $OLLAMA_URL"

echo "🔎 Health check: /api/tags"
HEALTH_OK=false
for i in $(seq 1 40); do
  if curl -sSf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    HEALTH_OK=true
    break
  fi
  sleep 5
done

if [ "$HEALTH_OK" != "true" ]; then
  echo "⚠️ Ollama health endpoint is not ready yet: $OLLAMA_URL/api/tags"
else
  echo "✅ Ollama is healthy"
fi

echo "$OLLAMA_URL" > /tmp/ollama-url.txt
echo "✅ Saved URL to /tmp/ollama-url.txt"

rm -f /tmp/gcloud-key.json
echo "✅ GKE Ollama deployment complete"
