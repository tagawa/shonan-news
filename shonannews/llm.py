import json

INTRO = """You are translating and summarizing a short Japanese local news item for an English-speaking audience."""
TENSE_RULE = """Today's date is {today}. Use whatever tense is factually correct relative to today: past tense if the event described has already happened, present or future tense if it has not. An event dated later than today has not happened yet, so describe it in the future tense."""
FIDELITY_RULE = """Preserve names, dates, and numbers exactly as given. Do not round numbers, invent details, or drop proper nouns. Write every Japanese name in Latin letters, never in Japanese characters. Write a present-day Japanese person's name given name first (Hanako Tanabe, not Tanabe Hanako). Keep people from before the Meiji era family name first (Minamoto no Yoritomo), and keep stage, ring and pen names as written (Shofukutei Tsurube)."""
SOURCE_RULE = """The description is often cut off mid-sentence. Cover only what the title and description actually state: never attribute a statement, plan or intention to anyone unless the source text contains it, and never add background, significance, or expected reactions of your own."""
ENGLISH_RULE = """Always respond in English, even if the source text below is already in English."""
PROSE_RULE = """Write plain prose only: no markdown formatting, no bullet points, no inline URLs. The output will be read aloud by text-to-speech, so it must be clean spoken sentences. Inside the title, lede, and summary, put quoted names in single quotes, never double quotes. Write dates in the lede and summary in words, e.g. 19 September, never in numbers. When the source gives the day of the week, keep it in parentheses after the date, e.g. 19 September (Sat); never work out a day of the week yourself. Never state a year unless the source states it."""
LEDE_RULE = """The lede is a single standalone sentence, maximum 30 words, that answers what happened, when, and where, on its own. It is not the first sentence of the summary reworded into a teaser. If the source does not specify a date, omit the "when" from the lede rather than using a placeholder phrase like "on an unspecified date"."""
LABEL_RULE = """Also classify the item. Set label to 'sport' only for competition results, athletes and sports teams, or sports events, clinics or lessons people take part in; not for board games such as shogi, fitness classes, yabusame or other ritual performances, or firefighters' rescue competitions. Set label to 'safety' only for disasters, disaster preparedness and drills, crime and fraud warnings, police and fire service news, or public-health warnings; not for a business promoting its own product or service, and not for an elected official's report or opinion column, even one about disasters. Set label to 'politics' only for elections and candidates, council or assembly votes and decisions, and policy announcements by mayors or political parties; not for a city simply running or announcing a service or event, not for honours or ceremonies that officials attend, and not for an elected official's own report or opinion column. In every other case, and whenever unsure, set label to null."""
JSON_FORM = """Respond with a single JSON object and nothing else, in this exact form:
{{"event_date": "<the event's date as YYYY-MM-DD, or null if the source gives none>", "has_happened": <true if the event has already happened as of today, otherwise false>, "title": "<English title>", "lede": "<one standalone sentence, max 30 words, covering what/when/where>", "summary": "<1 to 3 sentence English summary>", "label": <"sport", "safety", "politics", or null>}}"""
INPUT_BLOCK = """Title: {title}
Description: {description}
"""

# The measured rules every prompt that writes post text must carry verbatim.
RULE_PARAGRAPHS = (TENSE_RULE, FIDELITY_RULE, SOURCE_RULE, ENGLISH_RULE, PROSE_RULE, LEDE_RULE)

PROMPT_TEMPLATE = "\n\n".join((INTRO, *RULE_PARAGRAPHS, LABEL_RULE, JSON_FORM, INPUT_BLOCK))


class LLMCallError(Exception):
    pass


# Added only when an item has place readings, so an item without any gets the prompt it had
# before. Measured in two rounds; see the backend spec, "Place readings".
NAMES_SENTENCE = "Write every Japanese name in Latin letters, never in Japanese characters."
READINGS_SENTENCE = "When place readings are listed after the description, write those places with the readings given."


def with_readings(prompt, readings):
    if not readings:
        return prompt
    prompt = prompt.replace(NAMES_SENTENCE, f"{NAMES_SENTENCE} {READINGS_SENTENCE}", 1)
    return prompt + "Place readings: " + "; ".join(f"{key} = {reading}" for key, reading in readings) + "\n"


def build_prompt(title, description, today, readings=()):
    prompt = PROMPT_TEMPLATE.format(title=title, description=description or "(no description provided)", today=today)
    return with_readings(prompt, readings)


def complete(create_fn, prompt, model="gpt-6-luna", max_completion_tokens=4000, reasoning_effort="low"):
    try:
        response = create_fn(
            model=model,
            max_completion_tokens=max_completion_tokens,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            reasoning_effort=reasoning_effort,
        )
    except Exception as exc:
        raise LLMCallError(str(exc)) from exc

    choice = response.choices[0]
    if choice.finish_reason == "length":
        raise LLMCallError("Response was truncated (finish_reason=length)")

    return choice.message.content


def call_llm(create_fn, title, description, today, model="gpt-6-luna", max_completion_tokens=4000, reasoning_effort="low",
             readings=()):
    return complete(create_fn, build_prompt(title, description, today, readings), model, max_completion_tokens,
                    reasoning_effort)


JUDGE_PROMPT = """You are checking whether a new Japanese local news item reports the same story as a post already on our site.

They are the same story only if both report the same event or announcement at the same stage. These are different stories: an announcement of an upcoming event and a report after it took place; a profile of a person and a news item about their event or project; two different events with the same organiser, venue or date; two editions or years of a recurring event or series. Decide the stage from the Japanese headlines and the dates, not from the tense of the English post, which can be wrong: an event dated after one item was published and on or before the other was published means one is a preview and the other a report.

Respond with a single JSON object and nothing else, in this exact form:
{{"same_story": true or false}}

Post already on our site
Original Japanese headline: {a_source_title}
Published: {a_published}
Event date: {a_event_date}
Title: {a_title}
Lede: {a_lede}
Summary: {a_body}

New item
Published: {b_published}
Event date: {b_event_date}
Title: {b_title}
Description: {b_description}
"""


def _day(value):
    return str(value)[:10] if value else "unknown"


def build_judge_prompt(post_front, post_body, title, description, published, event_date):
    # Dates, because the English tense of an older post can be wrong; see the backend spec, "Story merge shadow".
    return JUDGE_PROMPT.format(a_source_title=post_front.get("source_title") or "", a_title=post_front.get("title", ""),
                               a_lede=post_front.get("lede") or "", a_body=post_body,
                               a_published=_day(post_front.get("source_date")),
                               a_event_date=_day(post_front.get("event_date")), b_published=_day(published),
                               b_event_date=_day(event_date), b_title=title,
                               b_description=description or "(no description provided)")


def call_judge(create_fn, post_front, post_body, title, description, published, event_date):
    return complete(create_fn, build_judge_prompt(post_front, post_body, title, description, published, event_date))


def parse_judge(raw):
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    value = data.get("same_story") if isinstance(data, dict) else None
    return value if isinstance(value, bool) else None


MERGE_INTRO = ("You are updating an English news post on our local news site with a new Japanese news item about the "
               "same story.")
MERGE_RULE = ("Rewrite the post so it includes every fact the new item adds. Keep every fact, name, date, time and "
              "number the post already states. If the new item gives a different figure, date or time for something "
              "the post states, keep both and name each source, for example: 'Kamakura Keizai Shimbun reported over "
              "3,000 visitors; Town News (Kamakura), 1,600.' Only when the new item explicitly corrects the post, list "
              "the change under corrections with the old and new values as written in the post and the new item. "
              # SOURCE_RULE stays verbatim; without this it reads as the new item alone and drops the post's facts.
              "In the rules above, 'the title and description' means the post already on our site and the new item "
              "together.")
MERGE_JSON_FORM = ('Respond with a single JSON object and nothing else, in this exact form:\n'
                   '{{"event_date": "<the event\'s date as YYYY-MM-DD, or null if the sources give none>", '
                   '"title": "<English title>", "lede": "<one standalone sentence, max 30 words, covering '
                   'what/when/where>", "summary": "<1 to 4 sentence English summary>", '
                   '"corrections": [{{"old": "<value in the post>", "new": "<value in the new item>"}}]}}')
MERGE_INPUT = ("Post already on our site (source: {a_source})\nTitle: {a_title}\nLede: {a_lede}\nSummary: {a_body}\n\n"
               "New item (source: {b_source})\nTitle: {title}\nDescription: {description}\n")


def build_merge_prompt(post_front, post_body, title, description, source_name, today, readings=()):
    # Imported here: merge imports validate, and keeping llm free of module-level cycles is simpler.
    from .merge import english_source_name
    template = "\n\n".join((MERGE_INTRO, *RULE_PARAGRAPHS, MERGE_RULE, MERGE_JSON_FORM, MERGE_INPUT))
    prompt = template.format(today=today, a_source=english_source_name(post_front.get("source_name")),
                             a_title=post_front.get("title", ""), a_lede=post_front.get("lede") or "", a_body=post_body,
                             b_source=english_source_name(source_name), title=title,
                             description=description or "(no description provided)")
    return with_readings(prompt, readings)


def call_merge(create_fn, post_front, post_body, title, description, source_name, today, readings=()):
    return complete(create_fn, build_merge_prompt(post_front, post_body, title, description, source_name, today, readings))
