from pydantic import BaseModel, ConfigDict

from app.identity.models import Role


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    role: Role
    is_active: bool
