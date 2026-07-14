from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional

class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    name: str = Field(..., min_length=1)
    roles: List[str] = Field(..., min_items=1)

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class StartupProfileUpdate(BaseModel):
    team_name: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None
    founded_year: Optional[int] = None

class EnterpriseProfileUpdate(BaseModel):
    company_name: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None
    competencies: Optional[List[str]] = None
    experience_years: Optional[int] = None
    is_available: Optional[bool] = None