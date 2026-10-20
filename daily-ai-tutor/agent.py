"""Daily AI learning agent.

Picks the next lesson from curriculum.json, asks Claude to write a
10-minute study note (concept + verified news + quiz) with web search,
saves it to notes/YYYY-MM-DD.md, and records progress in progress.json.

Usage:
    python agent.py             # generate today's note
    python agent.py --dry-run   # print the prompt without calling the API
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
CURRICULUM_PATH = BASE_DIR / "curriculum.json"
PROGRESS_PATH = BASE_DIR / "progress.json"
NOTES_DIR = BASE_DIR / "notes"

KST = timezone(timedelta(hours=9))
MAX_CONTINUATIONS = 5

SYSTEM_PROMPT = """당신은 한 명의 학습자를 위한 AI 기술 개인 튜터입니다.
매일 정해진 분량의 학습 노트를 Markdown으로 작성합니다.

작성 원칙:
- 학습자의 수준과 학습 시간을 지키세요. 분량이 넘치면 줄이세요.
- 전문 용어는 처음 나올 때 쉬운 말과 비유로 풀어 쓰세요.
- 사실 주장(수치, 날짜, 출시 정보, 정의 등)은 웹 검색으로 확인한 뒤에만 쓰세요.
  확인한 주요 정보 뒤에는 각주 번호를 [^1] 형식으로 붙이고,
  노트 마지막 '출처' 절에 [^1]: 제목 - URL 형식으로 모아 적으세요.
- 공식 문서, 논문, 원 발표 자료 등 1차 출처를 우선하세요.
- 검색으로 확인하지 못한 내용은 쓰지 않거나 '확인되지 않음'이라고 명시하세요.
- 노트 본문만 출력하세요. 인사말이나 작성 과정 설명은 넣지 마세요."""


def load_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def pick_lesson(curriculum, progress):
    """Return (next lesson, previous lesson or None). Restarts after the last lesson."""
    lessons = curriculum["lessons"]
    done = {entry["lesson_id"] for entry in progress["history"]}
    remaining = [lesson for lesson in lessons if lesson["id"] not in done]
    lesson = remaining[0] if remaining else lessons[len(progress["history"]) % len(lessons)]

    previous = None
    if progress["history"]:
        last_id = progress["history"][-1]["lesson_id"]
        previous = next((l for l in lessons if l["id"] == last_id), None)
    return lesson, previous


def build_prompt(config, lesson, previous, today):
    learner = config["learner"]
    review = (
        f"- 복습 퀴즈 1문제: 지난 학습 주제 '{previous['title']}'에서 출제\n"
        if previous
        else "- 복습 퀴즈: 첫 학습이므로 생략\n"
    )
    return f"""오늘 날짜: {today:%Y-%m-%d} (KST)

[학습자 프로필]
- 수준: {learner['level']}
- 하루 학습 시간: {learner['minutes_per_day']}분
- 관심 분야: {', '.join(learner['interests'])}
- 메모: {learner['notes']}

[오늘의 주제]
- 트랙: {lesson['track']}
- 주제: {lesson['title']}

[노트 구성] (각 절의 제목은 아래 이름 그대로 사용)
# {today:%Y-%m-%d} AI 학습 노트: {lesson['title']}
## 1. 오늘의 개념 (약 5분)
- 핵심 설명, 일상 비유 1개, 짧은 예시나 코드(필요할 때만, Python)
- 핵심 요약 3줄
## 2. 이번 주 AI 소식 (약 3분)
- 최근 {config['news_window_days']}일 이내에 발표된 소식 {config['news_items']}개
- 각 소식: 발표일, 한두 문장 요약, 입문자에게 왜 중요한지 한 문장
- 발표일을 확인할 수 없는 소식은 넣지 마세요.
## 3. 확인 퀴즈 (약 2분)
- 오늘 주제 퀴즈 2문제(객관식)
{review}- 정답과 해설은 <details><summary>정답 보기</summary> ... </details> 안에 넣기
## 4. 더 알아보기
- 입문자가 읽기 좋은 자료 1~2개
## 검증 메모
- 오늘 노트에서 교차 확인한 주요 사실과 확인 방법을 2~3줄로 적기
## 출처
- 본문 각주 [^n]에 대응하는 출처 목록
"""


def generate_note(config, prompt):
    import anthropic

    client = anthropic.Anthropic()
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": config["max_web_searches"]}]
    messages = [{"role": "user", "content": prompt}]

    for _ in range(MAX_CONTINUATIONS):
        with client.beta.messages.stream(
            model=config["model"],
            max_tokens=32000,
            system=SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            output_config={"effort": config["effort"]},
            tools=tools,
            messages=messages,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            response = stream.get_final_message()

        if response.stop_reason != "pause_turn":
            break
        # The server-side search loop paused; resend the partial turn to resume.
        messages = [messages[0], {"role": "assistant", "content": response.content}]

    if response.stop_reason == "refusal":
        raise RuntimeError(f"요청이 거절되었습니다: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("응답이 max_tokens에서 잘렸습니다. max_tokens를 늘려 주세요.")

    text_parts, cited = [], {}
    for block in response.content:
        if block.type != "text":
            continue
        text_parts.append(block.text)
        for citation in getattr(block, "citations", None) or []:
            url = getattr(citation, "url", None)
            if url:
                cited.setdefault(url, getattr(citation, "title", None) or url)

    note = "".join(text_parts).strip()
    if cited:
        lines = [f"- [{title}]({url})" for url, title in cited.items()]
        note += "\n\n---\n### 웹 검색 인용 기록 (자동 생성)\n" + "\n".join(lines) + "\n"
    return note, response


def main():
    parser = argparse.ArgumentParser(description="Daily AI learning agent")
    parser.add_argument("--dry-run", action="store_true", help="프롬프트만 출력하고 API를 호출하지 않음")
    args = parser.parse_args()

    config = load_json(CONFIG_PATH)
    curriculum = load_json(CURRICULUM_PATH)
    progress = load_json(PROGRESS_PATH, {"history": []})
    today = datetime.now(KST)

    if any(entry["date"] == f"{today:%Y-%m-%d}" for entry in progress["history"]):
        print("오늘 노트는 이미 생성되었습니다.")
        return 0

    lesson, previous = pick_lesson(curriculum, progress)
    prompt = build_prompt(config, lesson, previous, today)

    if args.dry_run:
        print(SYSTEM_PROMPT, prompt, sep="\n\n")
        return 0

    note, response = generate_note(config, prompt)

    NOTES_DIR.mkdir(exist_ok=True)
    note_path = NOTES_DIR / f"{today:%Y-%m-%d}.md"
    note_path.write_text(note + "\n", encoding="utf-8")

    progress["history"].append({
        "date": f"{today:%Y-%m-%d}",
        "lesson_id": lesson["id"],
        "title": lesson["title"],
        "model": response.model,
    })
    save_json(PROGRESS_PATH, progress)

    print(f"저장 완료: {note_path} ({lesson['title']})")
    print(f"토큰 사용량: 입력 {response.usage.input_tokens}, 출력 {response.usage.output_tokens}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
