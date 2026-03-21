import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    base_url="https://api.venice.ai/api/v1",
    api_key=os.environ["VENICE_API_KEY"],
)

response = client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Write a binary search in Python."}],
    temperature=1.0,
    max_tokens=900,
)

print(response.choices[0].message.content)
