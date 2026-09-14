# SurfaceID 1 대 다수 검색 실행

현재 스크립트 기준 이미지: `surfaceid-preprocess:0.2`, `surfaceid-runtime:0.5`.
Linux/WSL에서 `DB_PATH`는 `surfaceid-project` 폴더의 상위 경로입니다.

## 라이브러리 구축

구조 파일을 별도로 준비합니다. `structures.csv`는 `id,chain,file`, `library.csv`는 `id,chain,region` 열을 사용하며 region은 F입니다.

```csv
id,chain,file
LIB001,A,LIB001.pdb
LIB002,A,LIB002.pdb
```

```csv
id,chain,region
LIB001,A,F
LIB002,A,F
```

```bash
bash "$DB_PATH/surfaceid-project/scripts/surfaceid-1tomany.sh" build-library   --name full-v1   --pdb-dir "$DB_PATH/surfaceid-project/input/libraries/full-v1/pdb"   --structures "$DB_PATH/surfaceid-project/input/libraries/full-v1/structures.csv"   --catalog "$DB_PATH/surfaceid-project/input/libraries/full-v1/library.csv"
```

## 라이브러리 내부 query 검색

```bash
bash "$DB_PATH/surfaceid-project/scripts/surfaceid-1tomany.sh" query   --library full-v1 --query-id LIB001 --query-chain A
```

query의 surface NPZ, contacts 및 within 배열이 라이브러리에 있어야 합니다. 현재 상위 스크립트는 `--query-pdb`, `--scope`, `--xyz`, `--align-top`, `--no-align`을 지원하지 않습니다. 검색은 CPU 10개 제한으로 실행합니다.

결과는 `work/searches/<query>-<library>-<timestamp>/`에 저장됩니다. 원 검색 TSV와 `*_ranked_hits.tsv`, `*_ranked_surfaces.tsv`, `*_ranked_pdbs.tsv`, `hit_indices/`를 생성합니다. 이 스크립트는 별도 정렬 단계를 호출하지 않습니다. 입력은 PDB이며 자동 mmCIF 변환은 수행하지 않습니다.
