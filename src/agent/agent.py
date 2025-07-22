from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic import BaseModel
from pydantic_ai.providers.anthropic import AnthropicProvider
import asyncio
import requests
import logging

# Set up logging for debug output
logger = logging.getLogger('visa_agent_debug')
logger.setLevel(logging.DEBUG)

# Create a custom formatter for debug output
class DebugFormatter(logging.Formatter):
    def format(self, record):
        if record.levelname == 'DEBUG':
            return f"[DEBUG] {record.getMessage()}"
        return record.getMessage()

# Add console handler with custom formatter
console_handler = logging.StreamHandler()
console_handler.setFormatter(DebugFormatter())
logger.addHandler(console_handler)

class VisaCheckRequest(BaseModel):
    location: str
    application_id: str
    passport_number: str
    surname: str
    max_retries: int = 3

class VisaSubmitRequest(BaseModel):
    session_id: str
    captcha_solution: str

class AgentDependencies(BaseModel):
    api_base_url: str = "http://localhost:5000/api"

model = AnthropicModel(
    'claude-3-7-sonnet-latest', provider=AnthropicProvider()
)
agent = Agent(
    model=model,
    system_prompt="""You are a helpful and proactive visa status assistant that helps people check their visa application status.

REQUIRED INFORMATION:
To check visa status, you need: location, application_id, passport_number, surname

AVAILABLE TOOLS:
1. check_auto: Automatically checks visa status with built-in captcha resolution
   - Use this FIRST as it's the fastest method
   - If it succeeds, provide the status to the user immediately
   
2. check: Manual visa status check that returns a captcha image
   - Use this if check_auto fails
   - Returns: session_id and captcha image
   - You must save the captcha image and ask the user to solve it
   
3. submit: Submits the captcha solution with session_id
   - Use this after the user provides the captcha solution
   - Requires: session_id (from check tool) and captcha text

ERROR HANDLING AND DECISION MAKING:
- When ANY tool returns an error, you MUST:
  1. Inform the user about the specific error
  2. Automatically try the next available method
  3. Provide clear guidance on what's happening

- Decision flow:
  1. Always start with check_auto
  2. If check_auto fails → immediately use check tool WITHOUT asking
  3. If check returns captcha → save it and ask user to solve it
  4. If any network/connection errors → suggest retrying or checking internet
  5. If all methods fail → provide specific troubleshooting steps

INTERPRETING ERROR RESPONSES:
- Tools may return error dictionaries with:
  - error: true (indicates an error occurred)
  - error_type: "api_error", "timeout", "connection", or "unknown"
  - message: specific error details
  - suggestion: recommended action
- When you see these errors:
  - Extract and communicate the error message clearly
  - Follow the suggestion provided
  - Take automatic action based on error_type

IMPORTANT BEHAVIORS:
- Be proactive: Don't wait for user permission to try alternative methods
- Be informative: Always explain what went wrong and what you're doing next
- Be persistent: Try all available options before giving up
- Be helpful: If all fails, suggest specific solutions (check internet, try later, contact support)

RESPONSE EXAMPLES:
- If check_auto fails: "The automatic check failed. Let me try the manual method for you..."
- If network error: "There seems to be a connection issue. Let me retry with a different approach..."
- If captcha needed: "I need your help solving a captcha. Here's the image: [show captcha]. Please tell me what you see."
- DO NOT SHOW THE CAPTCHA IMAGE TO THE USER. JUST ASK FOR THE CAPTCHA TEXT.

Remember: Your goal is to successfully get the visa status using whatever method works, without unnecessary delays or user prompts."""
)


@agent.tool
def check_auto(ctx: RunContext[AgentDependencies], request: VisaCheckRequest) -> str:
    """
    This tool will check the visa status automatically. But the issue is it will try to resolve the captcha by itself. If it responds fine, you can use this tool. If not then you can use the other tools.
    """    
    api_url = f"{ctx.deps.api_base_url}/visa-status/check-auto"
    
    try:
        response = requests.post(api_url, json=request.model_dump(), timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            error_msg = {
                "error": True,
                "error_type": "api_error",
                "status_code": response.status_code,
                "message": f"API returned status code {response.status_code}",
                "details": response.text if response.text else "No error details available",
                "suggestion": "The automatic check failed. Try the manual method instead."
            }
            return str(error_msg)
    except requests.exceptions.Timeout:
        error_msg = {
            "error": True,
            "error_type": "timeout",
            "message": "Request timed out after 30 seconds",
            "suggestion": "The server is taking too long to respond. Try the manual method."
        }
        
        return str(error_msg)
    except requests.exceptions.ConnectionError:
        error_msg = {
            "error": True,
            "error_type": "connection",
            "message": "Could not connect to the API server",
            "suggestion": "Check your internet connection or the API server might be down."
        }
      
        return str(error_msg)
    except Exception as e:
        error_msg = {
            "error": True,
            "error_type": "unknown",
            "message": str(e),
            "suggestion": "An unexpected error occurred. Try the manual method."
        }
        return str(error_msg)

@agent.tool
def check(ctx: RunContext[AgentDependencies], request: VisaCheckRequest) -> str:
    """
    This tool will check the visa status manually. You will need to enter the location, application_id, passport_number, surname. It will respond with the captcha and session id. You can use this session id to check the visa status later. Also with captcha you need to save it and ask the user to put the captcha. 
    """
    
    api_url = f"{ctx.deps.api_base_url}/visa-status/check"
    
    try:
        response = requests.post(api_url, json=request.model_dump(), timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            error_msg = {
                "error": True,
                "error_type": "api_error",
                "status_code": response.status_code,
                "message": f"API returned status code {response.status_code}",
                "details": response.text if response.text else "No error details available",
                "suggestion": "The manual check also failed. There might be an issue with the visa checking service."
            }
            return str(error_msg)
    except requests.exceptions.Timeout:
        error_msg = {
            "error": True,
            "error_type": "timeout",
            "message": "Request timed out after 30 seconds",
            "suggestion": "The server is not responding. Please try again later."
        }
        
        return str(error_msg)
    except requests.exceptions.ConnectionError:
        error_msg = {
            "error": True,
            "error_type": "connection",
            "message": "Could not connect to the API server",
            "suggestion": "Please check your internet connection or try again later."
        }
        
        return str(error_msg)
    except Exception as e:
        error_msg = {
            "error": True,
            "error_type": "unknown",
            "message": str(e),
            "suggestion": "An unexpected error occurred. Please try again later."
        }
        
        return str(error_msg)

@agent.tool
def submit(ctx: RunContext[AgentDependencies], request: VisaSubmitRequest) -> str:
    """
    This tool will submit the visa status with captcha. You will need to enter the session id from previous tool call and captcha from user. 
    """
    
    
    api_url = f"{ctx.deps.api_base_url}/visa-status/submit"
    
    try:
        response = requests.post(api_url, json=request.model_dump(), timeout=30)
        if response.status_code == 200:
            logger.debug(f"✅ Success: {response.json()}")
            logger.debug("─────────────────────────────────────────\n")
            return response.json()
        else:
            error_msg = {
                "error": True,
                "error_type": "api_error",
                "status_code": response.status_code,
                "message": f"API returned status code {response.status_code}",
                "details": response.text if response.text else "No error details available",
                "suggestion": "The captcha might be incorrect or the session expired. Please try the process again."
            }
            
            return str(error_msg)
    except requests.exceptions.Timeout:
        error_msg = {
            "error": True,
            "error_type": "timeout",
            "message": "Request timed out after 30 seconds",
            "suggestion": "The submission is taking too long. Please try again."
        }
        
        return str(error_msg)
    except requests.exceptions.ConnectionError:
        error_msg = {
            "error": True,
            "error_type": "connection",
            "message": "Could not connect to the API server",
            "suggestion": "Connection lost during submission. Please check your internet and try again."
        }
        
        return str(error_msg)
    except Exception as e:
        error_msg = {
            "error": True,
            "error_type": "unknown",
            "message": str(e),
            "suggestion": "An unexpected error occurred during submission. Please try the whole process again."
        }
        
        return str(error_msg)
    






