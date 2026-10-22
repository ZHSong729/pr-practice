"""Adaptive daily AI learning coach.

Each day the coach picks a skill from skills.json based on what you have
already passed (spaced repetition with Leitner boxes), asks Claude to write a
short lesson with verified sources, quizzes you in the terminal, and adjusts
tomorrow's plan from your answers.

Usage:
    python coach.py             # today's interactive session
    python coach.py --status    # show your progress per skill
    python coach.py --dry-run   # show today's plan and prompt without calling the API
"""

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROFILE_PATH = BASE_DIR / "profile.json"
SKILLS_PATH = BASE_DIR / "skills.json"
STATE_PATH = BASE_DIR / "state.json"
SESSIONS_DIR = BASE_DIR / "sessions"

KST = timezone(timedelta(hours=9))
MAX_CONTINUATIONS = 5
# Days until the next review, by Leitner box. Box 0 means "not started".
REVIEW_INTERVALS = {1: 1, 2: 3, 3: 7, 4: 14, 5: 30}
MAX_BOX = 5
UNLOCK_BOX = 2  # a prerequisite counts as passed from this box up
RECENT_SESSIONS = 3
LOW_ACCURACY = 0.5
HIGH_ACCURACY = 0.85
MAX_WEAK_POINTS = 5

SYSTEM_PROMPT = """당신은 한 명의 학습자를 맡은 AI 기술 개인 코치입니다.
학습자의 수준, 학습 시간, 지난 학습 결과에 맞춰 짧은 학습 자료를 Markdown으로 씁니다.

작성 원칙:
- 정해진 학습 시간 안에 읽을 수 있는 분량을 지키세요.
- 전문 용어는 처음 나올 때 쉬운 말과 일상 비유로 풀어 쓰세요.
- 사실 주장(정의, 수치, 날짜, 출시 정보)은 웹 검색으로 확인한 뒤에만 쓰세요.
  주요 정보 뒤에는 [^1] 형식의 각주를 달고, 마지막 '출처' 절에
  [^1]: 제목 - URL 형식으로 모으세요. 공식 문서, 논문, 원 발표 자료를 우선하세요.
- 확인하지 못한 내용은 빼거나 '확인되지 않음'이라고 밝히세요.
- 본문만 출력하세요. 인사말이나 작성 과정 설명은 넣지 마세요."""

QUIZ_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "skill_id": {"type": "string"},
                    "concept": {"type": "string"},
                    "question": {"type": "string"},
                    "choices": {"type": "array", "items": {"type": "string"}},
                    "answer_index": {"type": "integer"},
                    "explanation": {"type": "string"},
                },
                "required": ["skill_id", "concept", "question", "choices", "answer_index", "explanation"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}


# ---------- state and planning (no API calls) ----------

def load_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def new_state():
    return {"skills": {}, "sessions": [], "weak_points": []}


def skill_box(state, skill_id):
    return state["skills"].get(skill_id, {}).get("box", 0)


def recent_accuracy(state):
    """Share of correct answers over the last few sessions, or None before the first one."""
    recent = state["sessions"][-RECENT_SESSIONS:]
    total = sum(s["total"] for s in recent)
    if not total:
        return None
    return sum(s["correct"] for s in recent) / total


def due_skills(skills, state, today):
    """Started skills whose review date has come, the shakiest first."""
    due = []
    for skill in skills:
        entry = state["skills"].get(skill["id"])
        if entry and date.fromisoformat(entry["due"]) <= today:
            due.append((entry["box"], entry["due"], skill))
    return [skill for _, _, skill in sorted(due, key=lambda d: (d[0], d[1]))]


def next_new_skill(skills, state):
    """First not-started skill whose prerequisites have all been passed."""
    for skill in skills:
        if skill_box(state, skill["id"]) == 0 and all(
            skill_box(state, p) >= UNLOCK_BOX for p in skill["prereqs"]
        ):
            return skill
    return None


def plan_today(skills, state, today):
    """Decide today's main skill, whether it is new or re-taught, and one review skill.

    When recent accuracy is low, the coach re-teaches the shakiest due skill
    instead of opening a new one.
    """
    due = due_skills(skills, state, today)
    accuracy = recent_accuracy(state)
    new = next_new_skill(skills, state)

    if new and not (due and accuracy is not None and accuracy < LOW_ACCURACY):
        main, mode = new, "new"
    elif due:
        main, mode = due[0], "reteach"
    elif new:
        main, mode = new, "new"
    else:
        # Everything started is passed and nothing is due: refresh the weakest skill.
        started = [s for s in skills if skill_box(state, s["id"]) > 0]
        main = min(started, key=lambda s: skill_box(state, s["id"]))
        mode = "reteach"

    review = next((s for s in due if s["id"] != main["id"]), None)
    return {"main": main, "mode": mode, "review": review, "accuracy": accuracy}


def difficulty_hint(accuracy):
    if accuracy is None:
        return "첫 학습입니다. 아주 기초부터 차근차근 설명하세요."
    if accuracy < LOW_ACCURACY:
        return "최근 정답률이 낮습니다. 더 쉬운 말과 다른 비유로, 개념 수를 줄여 설명하세요."
    if accuracy > HIGH_ACCURACY:
        return "최근 정답률이 높습니다. 입문 수준을 유지하되 한 단계 깊은 내용을 하나 더하세요."
    return "현재 난이도를 유지하세요."


def update_skill(state, skill_id, correct, total, today):
    """Move a skill between Leitner boxes from its quiz result and set the next review date."""
    box = max(skill_box(state, skill_id), 1)
    if correct == total:
        box = min(box + 1, MAX_BOX)
    elif correct * 2 < total:
        box = 1
    entry = state["skills"].setdefault(skill_id, {"attempts": 0, "correct": 0})
    entry["box"] = box
    entry["due"] = (today + timedelta(days=REVIEW_INTERVALS[box])).isoformat()
    entry["attempts"] += total
    entry["correct"] += correct
    entry["last_studied"] = today.isoformat()


def record_results(state, plan, questions, answers, today):
    """Apply quiz answers to the state: per-skill boxes, session log, weak points."""
    per_skill = {}
    for question, answer in zip(questions, answers):
        ok = answer == question["answer_index"]
        stats = per_skill.setdefault(question["skill_id"], [0, 0])
        stats[0] += ok
        stats[1] += 1
        if not ok:
            state["weak_points"].append({"skill_id": question["skill_id"], "concept": question["concept"]})
    state["weak_points"] = state["weak_points"][-MAX_WEAK_POINTS:]

    for skill_id, (correct, total) in per_skill.items():
        update_skill(state, skill_id, correct, total, today)

    correct = sum(c for c, _ in per_skill.values())
    state["sessions"].append({
        "date": today.isoformat(),
        "main": plan["main"]["id"],
        "mode": plan["mode"],
        "review": plan["review"]["id"] if plan["review"] else None,
        "correct": correct,
        "total": len(answers),
    })
    return correct


def check_footnotes(markdown):
    """Return footnote numbers used in the text but never defined, and defined but never used."""
    defined = set(re.findall(r"^\[\^(\d+)\]:", markdown, flags=re.MULTILINE))
    used = set(re.findall(r"\[\^(\d+)\](?!:)", markdown))
    return sorted(used - defined, key=int), sorted(defined - used, key=int)


# ---------- prompts ----------

def build_lesson_prompt(profile, plan, state, today):
    learner = profile["learner"]
    main = plan["main"]
    weak = [w["concept"] for w in state["weak_points"] if w["skill_id"] == main["id"]]
    mode_line = (
        "처음 배우는 주제입니다."
        if plan["mode"] == "new"
        else "이전에 배웠지만 아직 익숙하지 않은 주제입니다. 지난번과 다른 비유와 예시로 다시 설명하세요."
    )
    weak_line = f"- 지난번에 틀린 개념(꼭 다시 짚기): {', '.join(weak)}\n" if weak else ""
    return f"""오늘 날짜: {today:%Y-%m-%d} (KST)

[학습자]
- 수준: {learner['level']} / 하루 {learner['minutes_per_day']}분
- 목표: {learner['goal']}
- 관심 분야: {', '.join(learner['interests'])}
- 환경: {learner['environment']}
- 요청: {learner['style']}

[오늘의 주제]
- 트랙: {main['track']}
- 주제: {main['title']}
- 상태: {mode_line}
- 난이도 조절: {difficulty_hint(plan['accuracy'])}
{weak_line}
[구성] (절 제목은 그대로 사용)
# {today:%Y-%m-%d} {main['title']}
## 핵심 개념
- 핵심 설명, 일상 비유 1개, 필요할 때만 짧은 Python 예시
## 기억할 3줄
## 오늘의 AI 소식
- 최근 7일 안에 발표된, 오늘 주제와 관련 있는 소식 1개 (발표일과 한두 문장 요약). 발표일을 확인할 수 없으면 이 절에 '해당 없음'이라고 쓰세요.
## 검증 메모
- 교차 확인한 주요 사실과 확인 방법 2~3줄
## 출처
"""


def build_quiz_prompt(plan, lesson):
    main = plan["main"]
    review = plan["review"]
    review_line = (
        f"- skill_id '{review['id']}' ('{review['title']}') 복습 문제 1개: 위 학습 자료가 아닌 이 주제의 기초 개념에서 출제\n"
        if review
        else ""
    )
    return f"""아래 학습 자료를 읽은 입문자를 위한 객관식 퀴즈를 만드세요.

- skill_id '{main['id']}' 문제 2개: 학습 자료의 핵심 개념에서 출제
{review_line}- 보기는 4개, answer_index는 0부터 시작하는 정답 번호
- concept: 문제가 확인하는 개념을 짧은 명사구로
- explanation: 정답인 이유와 헷갈리기 쉬운 오답을 1~2문장으로
- 한국어로 작성

<lesson>
{lesson}
</lesson>"""


# ---------- Claude API ----------

def call_claude(client, profile, messages, tools=None, output_format=None):
    """Stream one request, resuming server-side tool loops that pause."""
    output_config = {"effort": profile["effort"]}
    if output_format:
        output_config["format"] = output_format
    kwargs = {"tools": tools} if tools else {}

    for _ in range(MAX_CONTINUATIONS):
        with client.beta.messages.stream(
            model=profile["model"],
            max_tokens=32000,
            system=SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            output_config=output_config,
            messages=messages,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            **kwargs,
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason != "pause_turn":
            break
        messages = [messages[0], {"role": "assistant", "content": response.content}]

    if response.stop_reason == "refusal":
        raise RuntimeError(f"요청이 거절되었습니다: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("응답이 max_tokens에서 잘렸습니다.")
    return response


def response_text(response):
    """Joined text blocks plus the URLs cited by web search."""
    parts, cited = [], {}
    for block in response.content:
        if block.type != "text":
            continue
        parts.append(block.text)
        for citation in getattr(block, "citations", None) or []:
            url = getattr(citation, "url", None)
            if url:
                cited.setdefault(url, getattr(citation, "title", None) or url)
    return "".join(parts).strip(), cited


def generate_lesson(client, profile, prompt):
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": profile["max_web_searches"]}]
    response = call_claude(client, profile, [{"role": "user", "content": prompt}], tools=tools)
    return response_text(response)


def generate_quiz(client, profile, plan, lesson):
    prompt = build_quiz_prompt(plan, lesson)
    response = call_claude(
        client, profile, [{"role": "user", "content": prompt}],
        output_format={"type": "json_schema", "schema": QUIZ_SCHEMA},
    )
    text, _ = response_text(response)
    questions = json.loads(text)["questions"]
    valid_ids = {plan["main"]["id"]} | ({plan["review"]["id"]} if plan["review"] else set())
    questions = [
        q for q in questions
        if q["skill_id"] in valid_ids and len(q["choices"]) >= 2 and 0 <= q["answer_index"] < len(q["choices"])
    ]
    if not questions:
        raise RuntimeError("퀴즈를 만들지 못했습니다. 다시 실행해 주세요.")
    return questions


# ---------- terminal session ----------

def ask_choice(question, ask=input):
    """Show one question and return the chosen index (0-based)."""
    print(f"\nQ. {question['question']}")
    for i, choice in enumerate(question["choices"], 1):
        print(f"  {i}) {choice}")
    while True:
        raw = ask(f"답 (1-{len(question['choices'])}): ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(question["choices"]):
            return int(raw) - 1
        print("번호로 입력해 주세요.")


def run_quiz(questions, ask=input):
    answers, lines = [], []
    for n, question in enumerate(questions, 1):
        answer = ask_choice(question, ask)
        answers.append(answer)
        ok = answer == question["answer_index"]
        right = question["choices"][question["answer_index"]]
        print(("정답입니다. " if ok else f"아쉬워요. 정답: {right}. ") + question["explanation"])
        lines.append(
            f"{n}. {question['question']}\n"
            f"   - 내 답: {question['choices'][answer]} ({'O' if ok else 'X'})\n"
            f"   - 정답: {right}\n   - 해설: {question['explanation']}"
        )
    return answers, lines


def print_status(skills, state, today):
    for skill in skills:
        entry = state["skills"].get(skill["id"])
        if entry:
            due = "복습 필요" if date.fromisoformat(entry["due"]) <= today else f"다음 복습 {entry['due']}"
            print(f"[{entry['box']}/{MAX_BOX}] {skill['title']} ({due})")
        else:
            locked = any(skill_box(state, p) < UNLOCK_BOX for p in skill["prereqs"])
            print(f"[ - ] {skill['title']} ({'잠김' if locked else '시작 가능'})")
    accuracy = recent_accuracy(state)
    if accuracy is not None:
        print(f"\n최근 {RECENT_SESSIONS}회 정답률: {accuracy:.0%}")


def describe_plan(plan):
    lines = [f"오늘의 주제: {plan['main']['title']} ({'새 주제' if plan['mode'] == 'new' else '다시 배우기'})"]
    if plan["review"]:
        lines.append(f"복습 문제: {plan['review']['title']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Adaptive daily AI learning coach")
    parser.add_argument("--status", action="store_true", help="스킬별 진도 보기")
    parser.add_argument("--dry-run", action="store_true", help="오늘 계획과 프롬프트만 출력 (API 호출 없음)")
    parser.add_argument("--force", action="store_true", help="오늘 이미 학습했어도 한 번 더 진행")
    args = parser.parse_args()

    profile = load_json(PROFILE_PATH)
    skills = load_json(SKILLS_PATH)["skills"]
    state = load_json(STATE_PATH, new_state())
    today = datetime.now(KST).date()

    if args.status:
        print_status(skills, state, today)
        return 0
    if not args.force and any(s["date"] == today.isoformat() for s in state["sessions"]):
        print("오늘 학습은 이미 마쳤습니다. 진도는 --status로 볼 수 있습니다.")
        return 0

    plan = plan_today(skills, state, today)
    prompt = build_lesson_prompt(profile, plan, state, today)
    print(describe_plan(plan))
    if args.dry_run:
        print("\n" + SYSTEM_PROMPT + "\n\n" + prompt)
        return 0

    import anthropic

    client = anthropic.Anthropic()
    print("\n학습 자료를 만드는 중입니다 (웹 검색 포함, 1~2분)...")
    lesson, cited = generate_lesson(client, profile, prompt)
    missing, unused = check_footnotes(lesson)
    print("\n" + lesson + "\n")
    if missing:
        print(f"[검증 경고] 출처가 없는 각주: {', '.join(missing)}")

    questions = generate_quiz(client, profile, plan, lesson)
    SESSIONS_DIR.mkdir(exist_ok=True)
    session_path = SESSIONS_DIR / f"{today.isoformat()}.md"
    report = [lesson, "\n---\n## 출처 자동 점검"]
    report.append(f"- 정의되지 않은 각주: {', '.join(missing) or '없음'}")
    report.append(f"- 본문에서 쓰이지 않은 출처: {', '.join(unused) or '없음'}")
    if cited:
        report.append("- 웹 검색 인용 기록 (API가 돌려준 URL):")
        report += [f"  - [{title}]({url})" for url, title in cited.items()]

    try:
        input("\n다 읽었으면 Enter를 눌러 퀴즈를 시작하세요.")
        answers, lines = run_quiz(questions)
    except (KeyboardInterrupt, EOFError):
        session_path.write_text("\n".join(report) + "\n", encoding="utf-8")
        print(f"\n퀴즈를 건너뛰었습니다. 학습 자료만 저장: {session_path}")
        return 0

    correct = record_results(state, plan, questions, answers, today)
    report.append(f"\n## 퀴즈 결과: {correct}/{len(answers)}")
    report += lines
    session_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    save_json(STATE_PATH, state)

    tomorrow = plan_today(skills, state, today + timedelta(days=1))
    print(f"\n오늘 결과: {correct}/{len(answers)}. 저장: {session_path}")
    print("내일 예정 -> " + describe_plan(tomorrow).replace("\n", " / "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
