# AI Coach (적응형 일일 학습 코치)

입문자를 위한 하루 10분 AI 학습 코치입니다. `daily-ai-tutor`는 정해진 순서대로 노트를 만들어 두기만 했는데,
AI Coach는 터미널에서 퀴즈를 직접 풀게 하고, 그 결과에 따라 다음 날 배울 내용을 바꿉니다.

## 하루 흐름 (약 10분)

1. **계획**: 지난 결과를 보고 오늘 배울 스킬 1개와 복습 스킬 1개를 고릅니다.
2. **학습 자료**: Claude가 웹 검색으로 사실을 확인한 뒤 짧은 자료를 씁니다
   (핵심 개념, 기억할 3줄, 관련 AI 소식 1개, 검증 메모, 각주 출처).
3. **퀴즈**: 오늘 주제 2문제와 복습 1문제를 터미널에서 풉니다. 답을 고르면 바로 해설이 나옵니다.
4. **기록**: 결과를 `state.json`에 저장하고, 내일 무엇을 배울지 보여 줍니다.

## 나에게 맞추는 방식

| 규칙 | 동작 |
| --- | --- |
| 스킬 맵 | `skills.json`의 24개 스킬에는 선수 스킬이 있습니다. 선수 스킬을 한 번 통과해야 다음 스킬이 열립니다. |
| 간격 반복 | 라이트너(Leitner) 상자 5단계를 씁니다[^1]. 다 맞히면 한 단계 올라가고, 절반 넘게 틀리면 1단계로 돌아갑니다. 단계별 다음 복습: 1일, 3일, 7일, 14일, 30일 |
| 다시 배우기 | 최근 3회 정답률이 50% 미만이면 새 주제 대신, 복습 날짜가 된 스킬 중 가장 약한 것을 다른 비유로 다시 배웁니다. |
| 난이도 | 정답률이 낮으면 더 쉽게, 85%를 넘으면 한 단계 깊게 쓰라고 지시합니다. |
| 약점 기억 | 틀린 문제의 개념을 기억해 두었다가, 그 스킬을 다시 배울 때 꼭 짚게 합니다. |

## 출처 검증

- 학습 자료의 주요 사실에는 각주 `[^n]`이 달리고, 마지막 '출처' 절에 URL이 모입니다.
- 실행할 때마다 각주를 점검해서 **출처가 없는 각주**와 **본문에서 쓰이지 않은 출처**를 기록합니다.
- API가 돌려준 웹 검색 인용 URL을 따로 기록하므로, 모델이 쓴 출처와 비교해 볼 수 있습니다.

## 파일

- `coach.py`: 코치 본체
- `profile.json`: 학습자 프로필(수준, 시간, 목표, 관심 분야)과 모델 설정
- `skills.json`: 스킬 맵 (ML 기초, LLM 앱/에이전트, MLOps/인프라)
- `state.json`: 스킬별 단계, 학습 기록, 약점 (첫 학습 후 생성)
- `sessions/YYYY-MM-DD.md`: 그날의 학습 자료, 출처 점검 결과, 퀴즈 결과

## 실행 (Windows PowerShell)

```powershell
cd ai-coach
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:ANTHROPIC_API_KEY = "sk-ant-..."   # Claude Console에서 발급
python coach.py --dry-run   # API 호출 없이 오늘 계획과 프롬프트 확인
python coach.py             # 오늘 학습 시작
python coach.py --status    # 스킬별 진도 보기
```

같은 날 두 번째 실행은 건너뜁니다. 한 번 더 하려면 `--force`를 붙이세요.
퀴즈 중 `Ctrl+C`로 멈추면 학습 자료만 저장하고 진도는 바꾸지 않습니다.

### 매일 오후 1시에 창 띄우기 (Windows 작업 스케줄러)

퀴즈를 직접 풀어야 하므로, 로그인한 상태에서 PowerShell 창이 열리게 등록합니다.

```powershell
schtasks /Create /SC DAILY /ST 13:00 /TN "AICoach" `
  /TR "powershell -NoExit -Command cd '$PWD'; .venv\Scripts\python.exe coach.py"
```

API 키는 사용자 환경 변수로 등록해 두세요: `setx ANTHROPIC_API_KEY "sk-ant-..."`

## 비용

하루 API 호출은 2번입니다(학습 자료 1번, 퀴즈 1번). 웹 검색은 학습 자료에서만 쓰고
`profile.json`의 `max_web_searches`(기본 6회)로 제한합니다.

- `claude-opus-5-5`: 입력 100만 토큰당 $4, 출력 $20[^2]
- `claude-sonnet-5-5`: 입력 $2, 출력 $10. 비용을 줄이려면 `profile.json`의 `model`을 바꾸세요[^2]
- 웹 검색: 1,000회당 $10, 검색 결과는 입력 토큰으로도 계산됩니다[^2]

## 테스트

```powershell
python -m unittest discover -s tests -v
```

## 출처

[^1]: Leitner system - https://en.wikipedia.org/wiki/Leitner_system (세바스티안 라이트너가 1972년 저서에서 소개한 5상자 플래시카드 방식)
[^2]: Pricing - Claude API Docs - https://platform.claude.com/docs/en/about-claude/pricing (2026-10-22 확인)
