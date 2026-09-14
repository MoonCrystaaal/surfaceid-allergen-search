# SurfaceID 원본과 로컬 수정 복원

- 원본: https://github.com/Sanofi-Public/LMR-SurfaceID.git
- 기준 커밋: `bc0d0148dfa0c34ec238b6a746902dff2198410d`
- 로컬 코드 차이: `surfaceid-local.patch` (검색 시 사전 계산 자료 재사용)
- 가중치: `models/model_final_002.pth`, 7,140,827 bytes
- 가중치 SHA-256: `63f6394df85f3b833e97e50a2e8a30c5eba702c4a146d11a0c4d2ca2690c91b1`

기존 `source/LMR-SurfaceID`는 수정된 Git 저장소이므로 그대로 보존합니다. 다음 명령은 **새 clone에서 해당 폴더가 없을 때만** 실행합니다. 이미 작업 중인 폴더가 있다면 그 상태를 먼저 백업하거나 별도 위치에서 확인합니다.

```bash
git clone https://github.com/Sanofi-Public/LMR-SurfaceID.git source/LMR-SurfaceID
git -C source/LMR-SurfaceID checkout --detach bc0d0148dfa0c34ec238b6a746902dff2198410d
git -C source/LMR-SurfaceID apply --check ../../patches/surfaceid-local.patch
git -C source/LMR-SurfaceID apply ../../patches/surfaceid-local.patch
sha256sum source/LMR-SurfaceID/models/model_final_002.pth
```

가중치가 LFS pointer로만 내려온 경우 Git LFS를 설치하고 원본 저장소에서 해당 가중치를 받아 위 크기·해시와 대조합니다. 현재 로컬 파일은 위 해시와 일치합니다. 원본의 모델 파일 추적 상태에 LFS 관련 차이가 있어 텍스트 코드 패치에서 제외했습니다. 원본 이력과 파일은 변경하지 않았습니다. 원본 라이선스와 저작권 표시는 원본 checkout의 LICENSE를 따릅니다.
