from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class LLMResponse:
    """Standardized response from any LLM adapter."""
    
    def __init__(
        self,
        content: str = "",
        model: str = "",
        usage: Optional[Dict] = None,
        raw_response: Optional[Any] = None
    ):
        self.content = content
        self.model = model
        self.usage = usage or {}
        self.raw_response = raw_response


class LLMAdapter(ABC):
    """
    Abstract base class for all LLM adapters.
    Every concrete adapter must implement this interface.
    """
    
    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 4000
    ) -> LLMResponse:
        """
        Send messages to LLM, return standardized response.
        
        Args:
            messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
            model: Specific model ID (adapter picks default if None)
            temperature: Sampling temperature
            max_tokens: Max tokens to generate
            
        Returns:
            LLMResponse with standardized fields
        """
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable adapter name."""
        pass
    
    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model ID."""
        pass