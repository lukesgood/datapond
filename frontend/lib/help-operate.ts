/** Operate guide: the profile files and the settings an operator most often changes.
 *  Commands and values keys stay untranslated. */
import type { L } from "@/lib/help-locale"
import type { Section } from "@/lib/help-ai-ops"

const l = (en: string, ko: string): L => ({ en, ko })

export const OPERATE_PROFILES: { file: string; use: L }[] = [
  { file: "values-prod-single.yaml", use: l("AWS reference: EC2/K3s node, Aurora, S3, Glue, Bedrock, Trino in-cluster, Polaris beside Glue", "AWS 기준 배포: EC2/K3s 노드, Aurora, S3, Glue, Bedrock, 클러스터 내 Trino, Glue 옆의 Polaris") },
  { file: "values-onprem.yaml", use: l("Self-hosted: MinIO, Polaris, Trino and the optional add-ons (32 GB+ for the full set)", "자체 운영: MinIO, Polaris, Trino와 선택 add-on (전체 구성은 32 GB 이상)") },
  { file: "values-foundation.yaml", use: l("Portable Core on AWS: AI layer only (pgvector, S3, Bedrock), no catalog or engine", "AWS의 Portable Core: AI 계층만 (pgvector, S3, Bedrock), 카탈로그·엔진 없음") },
  { file: "values-sovereign-core.yaml", use: l("Sovereign Core: AI layer only, with in-cluster MinIO and Ollama", "Sovereign Core: 클러스터 내 MinIO와 Ollama를 쓰는 AI 계층 전용") },
  { file: "values-aws.yaml", use: l("Compatibility overlay for an existing cluster; keeps whatever is already running", "기존 클러스터용 호환 오버레이. 이미 실행 중인 구성을 유지") },
]

export const OPERATE_PROFILES_TITLE = l("Profiles and values files", "프로필과 values 파일")
export const OPERATE_PROFILES_NOTE = l(
  "Each profile is a Helm values file under `helm/datapond/`. Put your changes in your own overlay with an extra `-f`, rather than editing the shipped file.",
  "프로필은 `helm/datapond/` 아래의 Helm values 파일입니다. 배포된 파일을 직접 고치지 말고, 추가 `-f`로 자신의 오버레이 파일에 변경 사항을 두세요.",
)

export const OPERATE_TOPICS: Section[] = [
  {
    title: l("Polaris beside Glue", "Glue 옆의 Polaris"),
    paras: [
      l("Several Iceberg catalogs can run side by side, each with its own grants. On the AWS reference Glue stays the default and Polaris (`polaris.enabled`, metadata in Aurora) is the Trino catalog `polaris_lake`. A sync picks its catalog with Target catalog.",
        "Iceberg 카탈로그를 여러 개 나란히 운영할 수 있고 카탈로그마다 권한이 따로 있습니다. AWS 기준 배포에서는 Glue가 기본이고 Polaris(`polaris.enabled`, 메타데이터는 Aurora)는 Trino 카탈로그 `polaris_lake`입니다. 동기화는 Target catalog로 카탈로그를 고릅니다."),
      l("A Polaris target must accept the source's storage location (`polaris.storage.extraAllowedLocations`). To move existing tables use Settings → Data catalogs → Export…: plan first, then apply. No data is copied.",
        "Polaris 대상은 원본의 스토리지 위치를 허용해야 합니다(`polaris.storage.extraAllowedLocations`). 기존 테이블을 옮기려면 Settings → Data catalogs → Export…를 쓰세요. 먼저 plan, 그다음 apply입니다. 데이터는 복사하지 않습니다."),
    ],
  },
  {
    title: l("Trino workers", "Trino 워커"),
    paras: [
      l("`trino.workers.replicas` defaults to 0: the coordinator does the work. With workers, the coordinator only plans and the workers read the same catalogs. Size them with `trino.workers.heap`, `trino.workers.maxMemoryPerNode` and `trino.workers.resources`. There is no autoscaling: change the number and upgrade. Trino restarts once.",
        "`trino.workers.replicas` 기본값은 0이며 코디네이터가 직접 처리합니다. 워커를 두면 코디네이터는 계획만 세우고 워커가 같은 카탈로그를 읽습니다. 크기는 `trino.workers.heap`, `trino.workers.maxMemoryPerNode`, `trino.workers.resources`로 정합니다. 자동 확장은 없으므로 숫자를 바꾸고 업그레이드하세요. Trino가 한 번 재시작됩니다."),
    ],
    code: "# my-overlay.yaml\ntrino:\n  workers:\n    replicas: 2",
  },
]
