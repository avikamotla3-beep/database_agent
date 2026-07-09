import os
import requests
from typing import List, Dict, Any, Optional

from .llm_abc import LLMAdapter, LLMResponse


class OpenRouterAdapter(LLMAdapter):
    """
    Connector for OpenRouter API.
    Provides access to multiple LLMs through single API key.
    """
    
    BASE_URL = "https://openrouter.ai/api/v1"
    
    # Model capabilities for orchestrator routing
    MODELS = {
        "anthropic/claude-3.5-sonnet": {
            "name": "Claude 3.5 Sonnet",
            "strengths": ["sql", "graph", "schema", "orchestration", "reasoning"]
        },
        "openai/gpt-4o-mini": {
            "name": "GPT-4o Mini",
            "strengths": ["simple", "cost_efficient", "fast"]
        },
        "deepseek/deepseek-r1": {
            "name": "DeepSeek R1",
            "strengths": ["coding", "reasoning", "math"]
        },
    }
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not set")
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost",
            "X-Title": "DB Agent"
        }
    
    @property
    def name(self) -> str:
        return "openrouter"
    
    @property
    def default_model(self) -> str:
        return "anthropic/claude-3.5-sonnet"
    
    def get_model_for_task(self, capability: str) -> str:
        """Pick best model for a given capability."""
        mapping = {
            "sql": "anthropic/claude-3.5-sonnet",
            "graph": "anthropic/claude-3.5-sonnet",
            "schema": "anthropic/claude-3.5-sonnet",
            "vector": "openai/gpt-4o-mini",
            "simple": "openai/gpt-4o-mini",
            "orchestration": "anthropic/claude-3.5-sonnet",
        }
        return mapping.get(capability, self.default_model)
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 4000
    ) -> LLMResponse:
        
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        try:
            r = requests.post(
                f"{self.BASE_URL}/chat/completions",
                headers=self.headers,
                json=payload,
                timeout=60
            )
            r.raise_for_status()
            data = r.json()
            
            choice = data["choices"][0]
            
            return LLMResponse(
                content=choice["message"].get("content", ""),
                model=data.get("model", model or self.default_model),
                usage=data.get("usage", {}),
                raw_response=data
            )
            
        except Exception as e:
            raise Exception(f"OpenRouter error: {str(e)}")