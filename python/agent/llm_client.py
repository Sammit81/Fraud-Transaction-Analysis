"""LLM client wrapper. Provider-agnostic so we can swap models easily."""
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Provider config — change these two lines to swap providers
BASE_URL = "https://openrouter.ai/api/v1"
MODEL = "openrouter/free"
API_KEY_ENV = "OPENROUTER_API_KEY"

client = OpenAI(
    base_url=BASE_URL,
    api_key=os.environ[API_KEY_ENV],
)


def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str = MODEL,
    temperature: float = 0.2,
) -> str:
    """Send a prompt to the LLM and return the raw text response.

    Low temperature because we want consistent analytical reasoning,
    not creative variation.
    """
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    return response.choices[0].message.content