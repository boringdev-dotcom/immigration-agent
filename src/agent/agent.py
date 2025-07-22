from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider
import asyncio

model = AnthropicModel(
    'claude-3-5-sonnet-latest', provider=AnthropicProvider(api_key='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')
)
agent = Agent(
    model=model,
    system_prompt="You are a helpful assistant that can answer questions and help with tasks."
)

@agent.tool


async def main():
    result = await agent.run("What is the capital of France?")
    print(result.output)

asyncio.run(main())