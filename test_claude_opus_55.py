from openai import OpenAI

# Initialize client with your proxy URL
client = OpenAI(
    base_url="http://localhost:4000",  # Your proxy URL
    api_key="your-proxy-api-key"       # Your proxy API key
)

# Non-streaming response with the current default model
response = client.chat.completions.create(
    model="claude-opus-5.5",
    messages=[{"role": "user", "content": "How do I optimize this SQL query?"}],
)

print(response.choices[0].message.content)