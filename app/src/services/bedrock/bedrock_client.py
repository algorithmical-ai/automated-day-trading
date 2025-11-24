"""
AWS Bedrock Client for LLM interactions
"""

import json
import boto3
from typing import Dict, Any, Optional
from app.src.common.loguru_logger import logger
from app.src.config.constants import (
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    AWS_DEFAULT_REGION,
    AWS_BEDROCK_MODEL_ID,
)


class BedrockClient:
    """Client for AWS Bedrock LLM interactions"""

    _bedrock_runtime = None

    @classmethod
    def _ensure_client(cls):
        """Initialize Bedrock runtime client if not already initialized"""
        if cls._bedrock_runtime:
            return

        if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
            cls._bedrock_runtime = boto3.client(
                "bedrock-runtime",
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                region_name=AWS_DEFAULT_REGION,
            )
        else:
            cls._bedrock_runtime = boto3.client(
                "bedrock-runtime", region_name=AWS_DEFAULT_REGION
            )

    @classmethod
    async def invoke_model(
        cls, prompt: str, max_tokens: int = 4000, temperature: float = 0.7
    ) -> Optional[str]:
        """
        Invoke AWS Bedrock model with a prompt

        Args:
            prompt: The prompt to send to the model
            max_tokens: Maximum tokens in response
            temperature: Temperature for generation (0.0-1.0)

        Returns:
            Model response text or None if error
        """
        try:
            cls._ensure_client()

            # Prepare the request body for Claude models
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            }

            # Run synchronous boto3 call in executor to make it async
            import asyncio

            loop = asyncio.get_event_loop()

            def _invoke():
                response = cls._bedrock_runtime.invoke_model(
                    modelId=AWS_BEDROCK_MODEL_ID, body=json.dumps(body)
                )
                return json.loads(response.get("body").read())

            response_body = await loop.run_in_executor(None, _invoke)

            # Extract text from Claude response
            if "content" in response_body:
                content = response_body["content"]
                if isinstance(content, list) and len(content) > 0:
                    text = content[0].get("text", "")
                    return text
                elif isinstance(content, str):
                    return content

            return None
        except Exception as e:
            logger.error(f"Error invoking Bedrock model: {str(e)}")
            return None
