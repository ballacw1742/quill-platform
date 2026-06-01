from pydantic import BaseModel, Field


class AxeInput(BaseModel):
    user_message: str = Field(description="The user's request to Axe.")
