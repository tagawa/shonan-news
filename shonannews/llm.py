PROMPT_TEMPLATE = """You are translating and summarizing a short Japanese local news item for an English-speaking audience.

Today's date is {today}. Use whatever tense is factually correct relative to today: past tense if the event described has already happened, present or future tense if it has not.

Preserve names, dates, and numbers exactly as given. Do not round numbers, invent details, or drop proper nouns.

Always respond in English, even if the source text below is already in English.

Write plain prose only: no markdown formatting, no bullet points, no inline URLs. The output will be read aloud by text-to-speech, so it must be clean spoken sentences.

The lede is a single standalone sentence, maximum 30 words, that answers what happened, when, and where, on its own. It is not the first sentence of the summary reworded into a teaser. If the source does not specify a date, omit the "when" from the lede rather than using a placeholder phrase like "on an unspecified date".

Respond with a single JSON object and nothing else, in this exact form:
{{"title": "<English title>", "lede": "<one standalone sentence, max 30 words, covering what/when/where>", "summary": "<2 to 4 sentence English summary>"}}

Title: {title}
Description: {description}
"""


class LLMCallError(Exception):
    pass


def build_prompt(title, description, today):
    return PROMPT_TEMPLATE.format(title=title, description=description or "(no description provided)", today=today)


def call_llm(create_fn, title, description, today, model="gpt-5-mini", max_completion_tokens=4000, reasoning_effort="minimal"):
    prompt = build_prompt(title, description, today)
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
