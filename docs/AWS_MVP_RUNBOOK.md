# AWS MVP Runbook — Bedrock RAG on S3 + Aurora pgvector

## 0. Prerequisites
- `terraform apply` complete (Tasks 4-5); Bedrock model access enabled.
- Instance profile `datapond-app-profile` attached to the K3s EC2 instance.

## 1. Seed credentials secret (Aurora) and deploy
    kubectl -n datapond create secret generic datapond-secrets \
      --from-literal=POSTGRES_USER=datapond \
      --from-literal=POSTGRES_PASSWORD=<db_master_password> \
      --from-literal=POSTGRES_DB=datapond \
      --from-literal=JWT_SECRET=<random> \
      --from-literal=INTERNAL_API_KEY=<random> \
      --dry-run=client -o yaml | kubectl apply -f -

    helm upgrade --install datapond helm/datapond -n datapond \
      -f helm/datapond/values-aws.yaml \
      --set externalDatabase.host=<aurora_endpoint> \
      --set storage.bucket=<bucket_name>

## 2. Wait for backend ready
    kubectl -n datapond rollout status deploy/backend
    kubectl -n datapond logs deploy/backend | grep -i "vector schema"   # ensure_vector_schema ran

## 3. Upload sample source docs to S3
    aws s3 cp ./samples/ s3://<bucket_name>/rag-samples/ --recursive   # *.md / *.txt

## 4. End-to-end RAG smoke test
    TOKEN=$(curl -s -X POST https://<domain>/api/auth/login \
      -d '{"username":"admin","password":"<pw>"}' -H 'Content-Type: application/json' | jq -r .access_token)

    # create collection
    curl -s -X POST https://<domain>/api/ai/collections -H "Authorization: Bearer $TOKEN" \
      -H 'Content-Type: application/json' -d '{"name":"mvp","description":"aws mvp"}'

    # ingest from S3 (uses IAM role; embeds via Bedrock Titan)
    curl -s -X POST https://<domain>/api/ai/collections/mvp/ingest-source \
      -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
      -d '{"type":"s3","bucket":"<bucket_name>","prefix":"rag-samples/","max_files":50}'
    # expect: {"success":true,"documents":N,"chunks":M,...}

    # RAG query (generation via Bedrock Claude)
    curl -s -X POST https://<domain>/api/ai/rag -H "Authorization: Bearer $TOKEN" \
      -H 'Content-Type: application/json' \
      -d '{"collection":"mvp","question":"<a question answerable from the docs>","k":5}'
    # expect: {"answer":"... [1] ...","citations":[...],"has_ai":true}

## 5. Pass criteria
- ingest-source returns documents > 0 and chunks > 0 (Titan embeddings succeeded).
- /api/ai/rag returns has_ai=true with non-empty citations referencing s3://<bucket> sources.
- backend logs show no 502 from embeddings and no egress-policy 403.
