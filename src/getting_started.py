import os

import httpx
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


# NinjaChat uses /chat instead of /chat/completions,
# so we rewrite the path on outgoing requests.
class NinjaChatTransport(httpx.HTTPTransport):
    def handle_request(self, request):
        request.url = request.url.copy_with(
            path=request.url.path.replace("/chat/completions", "/chat")
        )
        return super().handle_request(request)


client = OpenAI(
    base_url="https://www.ninjachat.ai/api/v1",
    api_key=os.environ["NINJA_API_KEY"],
    http_client=httpx.Client(transport=NinjaChatTransport()),
)

response = client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Write a binary search in Python"}],
)

print(response.choices[0].message.content)
