"""Console visa chat.

Run with:
    python src/agent/chat_console.py
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import sys
import logging

from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
    PartStartEvent,
    PartDeltaEvent,
    TextPartDelta,
)
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

# Initialize console for rich output
console = Console()

# Set up custom logging handler for debug output
class RichDebugHandler(logging.Handler):
    """Custom handler to format debug output with rich console"""
    
    def emit(self, record):
        try:
            msg = self.format(record)
            if '[DEBUG]' in msg:
                # Style debug lines differently
                if '─────' in msg:
                    console.print(f"[dim cyan]{msg}[/dim cyan]")
                elif '🔧' in msg or '📍' in msg or '📤' in msg:
                    console.print(f"[dim yellow]{msg}[/dim yellow]")
                elif '✅' in msg:
                    console.print(f"[dim green]{msg}[/dim green]")
                elif '❌' in msg or '⏱️' in msg or '🔌' in msg or '⚠️' in msg:
                    console.print(f"[dim red]{msg}[/dim red]")
                else:
                    console.print(f"[dim]{msg}[/dim]")
        except Exception:
            self.handleError(record)

# Configure the visa agent debug logger
visa_logger = logging.getLogger('visa_agent_debug')
visa_logger.handlers = []  # Clear any existing handlers
visa_logger.addHandler(RichDebugHandler())
visa_logger.setLevel(logging.DEBUG)

# Import the agent from the agent module using an absolute import path
import sys
import os
# Add the parent directory to the path so we can import from src.agent
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.agent.agent import agent, AgentDependencies
from pydantic_ai import Agent


class ChatSession:
    """Manages a chat session with message history."""
    
    def __init__(self, history_file: Optional[Path] = None):
        self.messages: List[ModelMessage] = []
        self.deps = AgentDependencies()
        self.history_file = history_file or Path("chat_history.json")
        self.load_history()
    
    def load_history(self):
        """Load chat history from file if it exists."""
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = f.read()
                    if data.strip():
                        self.messages = ModelMessagesTypeAdapter.validate_json(data)
                        console.print(f"[dim]Loaded {len(self.messages)} messages from history[/dim]")
            except Exception as e:
                console.print(f"[yellow]Warning: Could not load history: {e}[/yellow]")
    
    def save_history(self):
        """Save chat history to file."""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                messages_json = ModelMessagesTypeAdapter.dump_json(self.messages)
                f.write(messages_json.decode('utf-8'))
        except Exception as e:
            console.print(f"[red]Error saving history: {e}[/red]")
    
    def add_messages(self, messages: List[ModelMessage]):
        """Add new messages to the session."""
        self.messages.extend(messages)
        self.save_history()
    
    def display_message(self, role: str, content: str, timestamp: datetime):
        """Display a message in the console with formatting."""
        time_str = timestamp.strftime("%H:%M:%S")
        
        if role == "user":
            console.print(f"\n[bold blue]You[/bold blue] [dim]{time_str}[/dim]")
            console.print(Panel(content, border_style="blue"))
        else:
            console.print(f"\n[bold green]Assistant[/bold green] [dim]{time_str}[/dim]")
            # Use markdown rendering for assistant responses
            console.print(Panel(Markdown(content), border_style="green"))
    
    async def run_chat(self):
        """Run the interactive chat loop."""
        console.print("[bold magenta]Welcome to the Visa Chat Console![/bold magenta]")
        console.print("Type 'exit' or 'quit' to end the conversation.")
        console.print("Type 'clear' to clear the chat history.")
        console.print("Type 'history' to view all messages.\n")
        
        while True:
            try:
                # Get user input
                user_input = Prompt.ask("\n[bold blue]You[/bold blue]")
                
                # Handle special commands
                if user_input.lower() in ['exit', 'quit']:
                    console.print("\n[yellow]Goodbye![/yellow]")
                    break
                
                if user_input.lower() == 'clear':
                    self.messages = []
                    self.save_history()
                    console.print("[yellow]Chat history cleared.[/yellow]")
                    continue
                
                if user_input.lower() == 'history':
                    self.show_history()
                    continue
                
                # Display user message
                timestamp = datetime.now(tz=timezone.utc)
                self.display_message("user", user_input, timestamp)
                
                # Use agent.iter() instead of run_stream for better tool handling
                console.print(f"\n[bold green]Assistant[/bold green] [dim]{timestamp.strftime('%H:%M:%S')}[/dim]")
                console.print("[green]╭" + "─" * 93 + "╮[/green]")
                console.print("[green]│[/green] ", end="")
                
                full_response = ""
                line_length = 0
                max_line_length = 91  # Account for borders
                
                async with agent.iter(user_input, deps=self.deps, message_history=self.messages) as agent_run:
                    async for node in agent_run:
                        if Agent.is_model_request_node(node):
                            # Stream the model's response
                            async with node.stream(agent_run.ctx) as stream:
                                async for event in stream:
                                    # Handle different types of streaming events properly
                                    if isinstance(event, PartStartEvent):
                                        # A new part is starting (could be text, tool call, etc.)
                                        pass  # Just acknowledge the start, don't print anything
                                    elif isinstance(event, PartDeltaEvent):
                                        if isinstance(event.delta, TextPartDelta):
                                            # This is a text delta - the actual streaming text content
                                            content_delta = event.delta.content_delta
                                            if content_delta:
                                                full_response += content_delta
                                                
                                                # Process each character for proper line wrapping
                                                for char in content_delta:
                                                    if char == '\n':
                                                        # Pad the rest of the line and start a new one
                                                        console.print(" " * (max_line_length - line_length) + " [green]│[/green]")
                                                        console.print("[green]│[/green] ", end="")
                                                        line_length = 0
                                                    else:
                                                        # Check if we need to wrap
                                                        if line_length >= max_line_length:
                                                            console.print(" [green]│[/green]")
                                                            console.print("[green]│[/green] ", end="")
                                                            line_length = 0
                                                        
                                                        console.print(char, end="")
                                                        line_length += 1
                        elif Agent.is_call_tools_node(node):
                            # Handle tool calls - just process them silently
                            # Don't interrupt the text flow with tool indicators
                            pass
                        elif Agent.is_end_node(node):
                            # We've reached the end, get the final result
                            final_result = agent_run.result
                            if final_result and hasattr(final_result, 'output'):
                                # If we haven't captured the full response through streaming,
                                # use the final output
                                if not full_response and final_result.output:
                                    full_response = str(final_result.output)
                                    for char in full_response:
                                        if char == '\n':
                                            console.print(" " * (max_line_length - line_length) + " [green]│[/green]")
                                            console.print("[green]│[/green] ", end="")
                                            line_length = 0
                                        else:
                                            if line_length >= max_line_length:
                                                console.print(" [green]│[/green]")
                                                console.print("[green]│[/green] ", end="")
                                                line_length = 0
                                            console.print(char, end="")
                                            line_length += 1
                
                # Finish the last line and close the panel
                if line_length > 0:
                    console.print(" " * (max_line_length - line_length) + " [green]│[/green]")
                console.print("[green]╰" + "─" * 93 + "╯[/green]")
                
                # Add messages to history after the run completes
                if agent_run.result:
                    self.add_messages(agent_run.result.new_messages())
                
            except KeyboardInterrupt:
                console.print("\n\n[yellow]Interrupted. Type 'exit' to quit.[/yellow]")
                continue
            except Exception as e:
                console.print(f"\n[red]Error: {e}[/red]")
                continue
    
    def show_history(self):
        """Display the full chat history."""
        if not self.messages:
            console.print("[yellow]No chat history.[/yellow]")
            return
        
        console.print("\n[bold]Chat History:[/bold]")
        for msg in self.messages:
            first_part = msg.parts[0]
            if isinstance(msg, ModelRequest) and isinstance(first_part, UserPromptPart):
                if isinstance(first_part.content, str):
                    self.display_message("user", first_part.content, first_part.timestamp)
            elif isinstance(msg, ModelResponse) and isinstance(first_part, TextPart):
                self.display_message("model", first_part.content, msg.timestamp)


async def main():
    """Main entry point for the chat application."""
    # You can specify a custom history file path here
    session = ChatSession()
    
    try:
        await session.run_chat()
    except Exception as e:
        console.print(f"[red]Fatal error: {e}[/red]")
    finally:
        # Ensure history is saved on exit
        session.save_history()


if __name__ == "__main__":
    asyncio.run(main()) 