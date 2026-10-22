"""
Local Ollama Inference Connector.
Executes grammar-constrained LLM inferences via Ollama's HTTP API.
"""

import json
import logging
from typing import Any, Dict, List, Optional
import httpx
from app.config import OllamaConfig, get_settings
from app.schemas import EmailTriageResult

logger = logging.getLogger(__name__)


class OllamaClientError(Exception):
    """Base exception for Ollama connector failures."""
    pass


class OllamaConnectionError(OllamaClientError):
    """Raised when Ollama daemon is unreachable."""
    pass


class OllamaModelNotFoundError(OllamaClientError):
    """Raised when the specified model is not downloaded in Ollama."""
    pass


class OllamaClient:
    def __init__(self, config: Optional[OllamaConfig] = None):
        self.config = config or get_settings().ollama
        self.base_url = self.config.base_url.rstrip("/")
        self.timeout = httpx.Timeout(
            timeout=self.config.timeout_seconds,
            connect=5.0
        )

    async def check_health(self) -> Dict[str, Any]:
        """
        Pings Ollama's /api/tags to verify daemon status and model availability.
        """
        url = f"{self.base_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                models = [m.get("name") for m in data.get("models", [])]
                
                # Check if model is pulled (matches name or name:latest)
                model_name = self.config.model
                has_model = any(
                    m == model_name or m.startswith(f"{model_name}:") or model_name.startswith(f"{m}:")
                    for m in models
                )
                return {
                    "online": True,
                    "available_models": models,
                    "configured_model": model_name,
                    "model_installed": has_model
                }
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise OllamaConnectionError(
                f"Cannot connect to Ollama daemon at {self.base_url}. Ensure 'ollama serve' is running."
            ) from e
        except Exception as e:
            raise OllamaClientError(f"Health check failed: {str(e)}") from e

    async def triage_email(self, messages: List[Dict[str, str]]) -> EmailTriageResult:
        """
        Sends grounded triage prompt to Ollama with grammar-constrained JSON formatting.
        Enforces temperature: 0.0 for deterministic extraction.
        """
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "format": EmailTriageResult.model_json_schema(),
            "options": {
                "temperature": 0.0,
            }
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                
                if response.status_code == 404:
                    raise OllamaModelNotFoundError(
                        f"Model '{self.config.model}' not found in Ollama. Run: ollama pull {self.config.model}"
                    )
                
                response.raise_for_status()
                data = response.json()
                raw_content = data.get("message", {}).get("content", "")

                # Parse and validate against Pydantic schema
                return EmailTriageResult.model_validate_json(raw_content)

        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise OllamaConnectionError(
                f"Failed to reach Ollama at {self.base_url}. Is the service running?"
            ) from e
        except OllamaClientError:
            raise
        except Exception as e:
            logger.error(f"Ollama inference error: {str(e)}")
            raise OllamaClientError(f"Triage inference failed: {str(e)}") from e

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2
    ) -> Dict[str, Any]:
        """
        Executes a multi-turn chat completion turn with optional tool definitions.
        Used by the interactive ReAct Co-Pilot harness.
        """
        url = f"{self.base_url}/api/chat"
        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
            }
        }
        if tools:
            payload["tools"] = tools

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                
                if response.status_code == 404:
                    raise OllamaModelNotFoundError(
                        f"Model '{self.config.model}' not found in Ollama. Run: ollama pull {self.config.model}"
                    )
                
                response.raise_for_status()
                data = response.json()
                return data.get("message", {})

        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise OllamaConnectionError(
                f"Failed to reach Ollama at {self.base_url}. Is the service running?"
            ) from e
        except OllamaClientError:
            raise
        except Exception as e:
            logger.error(f"Ollama chat completion error: {str(e)}")
            raise OllamaClientError(f"Chat completion failed: {str(e)}") from e

