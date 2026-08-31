# reference/ — 마지막 번들 원본 (diff 대조용)

여기에 마지막 번들의 아래 6개 파일을 넣습니다.

- `verifier.py`
- `kats_client.py`
- `scorer.py`
- `models.py`
- `watchlist.py`
- `kats_field_map.yaml`

용도는 **대조 전용**입니다. 이 폴더의 파일은 import 되지 않고, 테스트에도
들어가지 않습니다. `sourcing_guard/` 쪽이 실제 동작하는 코드입니다.

## 왜 필요한가

에이전트 작업분이 오래된 스냅샷 기반이라, 번들에 이미 구현된 A·B·C
(certState 유효성 판정 / 콤마 목록 분해 / 국내·국외 의미 차이)를
중복 구현할 뻔했습니다. 재작성 대신 diff 로 **동작 계약이 다른 지점만**
찾아내기 위한 폴더입니다.

특히 `certState` 매핑은 "어느 상태를 RED 로 볼지"가 제품 판단이므로
두 벌이 생기면 안 됩니다. 번들의 `_CERT_STATE_FINDING` 을 정본으로 씁니다.

## 대조가 끝나면

diff 결과를 반영한 뒤 이 폴더는 지웁니다. 오래 두면 어느 쪽이 정본인지
헷갈리는 두 번째 사본이 됩니다.
