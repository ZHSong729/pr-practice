# Daily AI Tutor

입문자를 위한 하루 10분 AI 학습 에이전트입니다. 매일 커리큘럼에서 다음 주제를 골라
Claude API(웹 검색 포함)로 학습 노트를 만들고 `notes/YYYY-MM-DD.md`에 저장합니다.

## 하루 노트 구성 (약 10분)

| 절 | 시간 | 내용 |
| --- | --- | --- |
| 1. 오늘의 개념 | 5분 | 커리큘럼 주제 설명, 비유, 요약 3줄 |
| 2. 이번 주 AI 소식 | 3분 | 최근 7일 소식 3개 (발표일 확인된 것만) |
| 3. 확인 퀴즈 | 2분 | 오늘 주제 2문제 + 지난 주제 복습 1문제 |
| 4. 더 알아보기 | - | 추가 자료 1~2개 |
| 검증 메모 / 출처 | - | 교차 확인한 사실, 각주 `[^n]` 출처 목록 |

노트 끝에는 API가 돌려준 웹 검색 인용(citation)에서 URL을 모은
"웹 검색 인용 기록 (자동 생성)"이 붙습니다. 모델이 쓴 각주 출처와 비교해 보면
출처를 검증할 수 있습니다.

## 파일

- `agent.py`: 에이전트 본체
- `config.json`: 학습자 프로필(수준, 학습 시간, 관심 분야), 모델, 뉴스 개수
- `curriculum.json`: 입문자용 주제 30개 (ML 기초, LLM 앱/에이전트, MLOps/인프라). 위에서부터 진행
- `progress.json`: 학습 기록 (첫 실행 때 생성)
- `notes/`: 생성된 학습 노트

## 로컬 실행 (Windows PowerShell)

```powershell
cd daily-ai-tutor
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:ANTHROPIC_API_KEY = "sk-ant-..."   # Claude Console에서 발급
python agent.py --dry-run   # API 호출 없이 프롬프트만 확인
python agent.py             # 오늘 노트 생성
```

같은 날 두 번 실행하면 새로 만들지 않습니다. 다시 만들려면 `progress.json`에서 오늘 항목을 지우세요.

### 매일 오후 1시 자동 실행 (Windows 작업 스케줄러)

```powershell
schtasks /Create /SC DAILY /ST 13:00 /TN "DailyAITutor" `
  /TR "powershell -NoProfile -Command cd '$PWD'; .venv\Scripts\python.exe agent.py"
```

API 키는 사용자 환경 변수로 등록해 두세요: `setx ANTHROPIC_API_KEY "sk-ant-..."`

## GitHub Actions로 자동 실행

`.github/workflows/daily-ai-tutor.yml`이 매일 03:50 UTC(12:50 KST)에 실행되어 노트를 커밋합니다.

1. 저장소 Settings > Secrets and variables > Actions에 `ANTHROPIC_API_KEY` 등록
2. 워크플로 파일을 기본 브랜치(main)에 병합 (예약 실행은 기본 브랜치에서만 동작)
3. Actions 탭에서 "Daily AI Tutor" > Run workflow로 바로 시험 실행 가능

참고: 예약 실행은 GitHub 부하에 따라 늦어질 수 있고, 공개 저장소에서 60일간 활동이 없으면 자동으로 꺼집니다.

## 비용

모델은 `claude-opus-5-5`(입력 100만 토큰당 $4, 출력 $20), 웹 검색은 1,000회당 $10입니다.
하루 검색은 `config.json`의 `max_web_searches`(기본 8회)로 제한합니다.
비용을 줄이려면 `config.json`에서 `model`을 `claude-sonnet-5-5`로 바꾸세요.

## 테스트

```powershell
python -m unittest discover -s tests -v
```
