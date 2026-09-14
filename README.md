# SurfaceID 알레르겐 표면 검색 워크플로

기존 LMR-SurfaceID와 MaSIF를 연결하는 Docker 환경, 라이브러리 구축, 캐시 재사용 검색 및 후보 순위 정리 코드입니다. 원 모델의 신규 개발 또는 학습 코드는 아닙니다.

## 구성

- `docker/preprocess/`: MaSIF 전처리와 NPZ 변환, 패치당 정점 수 200 설정
- `docker/runtime/`: CPU descriptor·검색 환경, 입력 검증 및 순위 정리
- `scripts/surfaceid-1tomany.sh`: 전체 표면 라이브러리 구축과 라이브러리 내부 query 검색
- `patches/`: 원본 SurfaceID에 적용한 로컬 코드 변경과 출처·복원 안내
- `input/`: 소형 CSV 목록; 실제 구조는 별도 준비
- `work/`: 생성 결과와 캐시, Git 제외

## 재현 환경

Linux 또는 WSL의 Bash, Docker, Git이 필요합니다. 먼저 [원본 코드 복원 안내](patches/README.md)에 따라 `source/LMR-SurfaceID`를 준비하고, 저장소 루트에서 실행합니다.

```bash
docker build -f docker/preprocess/Dockerfile -t surfaceid-preprocess:0.2 .
docker build -f docker/runtime/Dockerfile -t surfaceid-runtime:0.5 .
export DB_PATH="$(dirname "$PWD")"
bash scripts/surfaceid-1tomany.sh --help
```

폴더 이름은 `surfaceid-project`로 두는 것을 기준으로 작성했습니다. [라이브러리 구축과 검색 예시](scripts/README-1tomany.md)에 전체 실행 흐름을 정리했습니다. 현재 최상위 스크립트는 라이브러리에 이미 전처리된 query만 받으며, 외부 query PDB·XYZ 제한 영역·정렬 옵션은 받지 않습니다. 하위 runtime에 있는 기능과 최상위 스크립트에서 실제로 제공하는 기능은 범위가 다릅니다.

## 점수와 범위

`frac_geo`는 query 확장 영역과 library 영역의 hit 비율의 기하평균입니다. `rank_hits.py`는 frac_geo 내림차순으로 정렬하고 surface 및 PDB ID별 최상위 hit를 남깁니다. 해당 값은 교차반응 확률이 아닙니다. 보고서용 동점 기대 지표는 Cross-React 프로젝트의 `benchmark_ranking_metrics.py`에서 별도로 계산합니다.

`REUSE_PRECOMPUTED` 수정은 descriptor 및 within 정보를 재사용합니다. 검색마다 필요한 거리 계산까지 없애는 기능은 아니며 실행 시간 개선을 보장하지 않습니다. Cα·Cβ만 남기는 입력 실험은 현재 성공한 표준 실행 절차로 포함하지 않습니다.

## Git과 외부 코드

중첩된 원본 Git 이력과 remote는 보존했습니다. 상위 저장소는 원본 checkout 전체를 제외하고, 기준 커밋과 텍스트 패치로 의존성을 기록합니다. 모델 가중치는 SHA-256으로 확인하며 Git에 중복 추가하지 않습니다. 원본 LICENSE는 원본 저장소를 따릅니다.

이 워크플로 자체의 원격 저장소는 아직 설정되지 않았습니다. 보고서에는 본인 저장소 URL과 제출 커밋을 적고, Sanofi 원본 URL과 기준 커밋은 별도로 구분해 적습니다.

최종 보고서의 30 query 비교용 소형 순위와 라벨은 Cross-React 제출 저장소의 `submission/benchmark/`에 함께 보관했습니다. SurfaceID의 `work/benchmarks/` 아래 자료는 중간 작업 요약으로 남겨 둔 것입니다.
