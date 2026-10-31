# 결과 보고서: 인터랙티브 HTML

단일 HTML 파일(외부 의존 없음, 데이터는 페이지 안에 JSON으로 내장). 탐색 중 하네스에서 보여준 모든 시각 요소를 포함한다.

## 페이지 구성
1. 상단 요약: 문제 정의(관측 / 사용자 해석 / 닫힌 길), 고른 수, 종료 사유
2. Blueprint 탐색기
   - 거시 Blueprint에서 시작. 블록 클릭 → 그 블록으로 Lens를 좁혀 다음 깊이의 Blueprint로 전환
   - Lens 안은 실선 후보, 밖은 거리에 따라 흐려지는 점선 파급
   - 자식 Lens(이식 등)는 후보 카드를 클릭해 진입, 빵부스러기 경로로 복귀
3. 스프린트 타임라인: 스프린트별 단계·Lens·목표·요약·확인된 사실·변경량(절단 시점 표시), Blueprint 버전 변화
4. 후보 카드: 출처 링크, 통했던 조건, 코드/조건 이식 판정, 반사실 검정 결과와 검정 강도
5. 가치 비교 테이블: 열 클릭 정렬, 가중치 조절 시 순위 재계산, 축별 근거 툴팁
6. 버린 후보: 접힌 상태로 두고 버린 이유와 시점 표시
6-2. 사용자 제안: 제안마다 언제 들어와 어느 스프린트에서 어떻게 따져졌는지, 채택·보류·기각과 그 이유
6-1. Claude가 대신 정한 것: 응답이 없어 자율로 정한 결정마다 요청 내용, 고른 것, 이유, 되돌리는 방법 (references/autonomous-decision.md)
7. 남은 불확실성과 다음 실험

## 격언
각 단계 섹션의 머리말에 그 단계의 격언 원문과 번역을 출처와 함께 둔다(`config/values.yaml`). 원문을 먼저, 번역은 번역자 표기와 함께.

## 데이터 형식
페이지는 아래 객체 하나를 렌더한다. 탐색 중 기록을 그대로 쌓으면 된다.

```json
{
  "problem": {"observations": [], "user_interpretation": "", "closed_paths": []},
  "scopes": [{"id": "", "parent": null, "depth": 0, "spec": {"blocks": [], "scope": [], "candidates": {}, "ripples": []}}],
  "loops": [{"n": 1, "scope_id": "", "changes": [], "delta": 0, "top_choice": ""}],
  "candidates": [{"id": "", "scope_id": "", "source": "", "worked_under": "", "port_code": "", "port_condition": "", "counterfactual": {"strength": "", "result": ""}, "status": "active|dropped", "drop_reason": ""}],
  "table": {"axes": [], "weights": {}, "scores": {}},
  "termination": {"rule": "", "note": ""},
  "open_questions": []
}
```
