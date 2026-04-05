# backend/app/services/pdf_service.py
from typing import List, Dict, Optional
import requests
from datetime import datetime, timezone
import logging
from app import db
from app.models.download import Prompts
import requests


class PromptService:
    def __init__(self, cache_service=None):
        self.session = requests.Session()
        self.cache_service = cache_service
        self.logger = logging.getLogger(__name__)

    def get_prompts(self):
        try:
            if self.cache_service and (
                cached_prompts := self.cache_service.get("all_prompts")
            ):
                self.logger.info("Returning prompts from cache")
                return cached_prompts

            prompts = Prompts.query.all()

            if self.cache_service:
                self.cache_service.set("all_prompts", prompts)

            self.logger.info("Retrieved all prompts successfully")
            return prompts
        except Exception as e:
            self.logger.error(f"Error retrieving prompts: {str(e)}")
            raise

    def get_prompt(self, prompt_id: int) -> Optional[Prompts]:
        try:
            # print(type(prompt_id))
            if self.cache_service and (
                cached_prompt := self.cache_service.get(f"prompt_{prompt_id}")
            ):
                self.logger.info(f"Returning prompt {prompt_id} from cache")
                return cached_prompt

            prompt = Prompts.query.get(prompt_id)

            if self.cache_service:
                self.cache_service.set(f"prompt_{prompt_id}", prompt)

            self.logger.info(f"Retrieved prompt {prompt_id} successfully")
            return prompt
        except Exception as e:
            self.logger.error(f"Error retrieving prompt {prompt_id}: {str(e)}")
            raise

    def create_prompt(self, prompt: str) -> Optional[Prompts]:
        try:
            # print(prompt)
            new_prompt = Prompts(prompt=prompt, timestamp=datetime.now(timezone.utc))
            db.session.add(new_prompt)
            db.session.commit()

            if self.cache_service:
                self.cache_service.delete("all_prompts")  # Invalidate prompt list cache

            self.logger.info(f"Prompt created successfully with ID {new_prompt.id}")
            return new_prompt
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error creating prompt: {str(e)}")
            raise

    def update_prompt(self, prompt_id: int, new_text: str) -> Optional[Prompts]:
        try:
            prompt = Prompts.query.get(prompt_id)
            if not prompt:
                self.logger.warning(f"Prompt with ID {prompt_id} not found")
                return None

            prompt.prompt = new_text
            prompt.timestamp = datetime.now(timezone.utc)
            db.session.commit()

            if self.cache_service:
                self.cache_service.delete(
                    f"prompt_{prompt_id}"
                )  # Invalidate cache for the specific prompt

            self.logger.info(f"Prompt {prompt_id} updated successfully")
            return prompt
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error updating prompt {prompt_id}: {str(e)}")
            raise

    def delete_prompt(self, prompt_id: int) -> Optional[Prompts]:
        try:
            prompt = Prompts.query.get(prompt_id)
            if not prompt:
                self.logger.warning(f"Prompt with ID {prompt_id} not found")
                return None

            db.session.delete(prompt)
            db.session.commit()

            if self.cache_service:
                self.cache_service.delete(f"prompt_{prompt_id}")
                self.cache_service.delete("all_prompts")  # Invalidate prompt list cache

            self.logger.info(f"Prompt {prompt_id} deleted successfully")
            return prompt
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error deleting prompt {prompt_id}: {str(e)}")
            raise
