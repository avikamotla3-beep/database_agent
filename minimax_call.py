from openai import OpenAI

api_key = "sk-cp-MROGqoQmQHUaooqkGNBZRUpsCXwjc9w2zSWPLW9JFZ5hAROk13S35faan4bWqAN7r-HaVc-NzKFX4Ebwq8HDZKjNPCDDuaFm6JCE--NhKWfqFJPqPC7SjGQ"

client = OpenAI(
    base_url="https://api.minimax.io/v1",
    api_key=api_key,
)

response = client.chat.completions.create(
    model="MiniMax-M3",
    messages=[
        {"role": "user", "content": "whats my name?"},
    ],
)

print(response.choices[0].message.content)