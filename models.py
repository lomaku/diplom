import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Boolean, DateTime, Integer, Text,
    ForeignKey, UniqueConstraint, CheckConstraint, Enum as SAEnum,
    Numeric
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import DeclarativeBase, relationship
import enum

class Base(DeclarativeBase):
    pass

# ---------- Enums ----------
class ProjectStatus(str, enum.Enum):
    draft = "draft"
    submitted = "submitted"
    under_review = "under_review"
    evaluated = "evaluated"
    archived = "archived"

class RequestStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    closed = "closed"
    archived = "archived"

class ReviewStatus(str, enum.Enum):
    assigned = "assigned"
    in_progress = "in_progress"
    completed = "completed"

# ---------- Users & Roles ----------
class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    avatar_url = Column(Text)
    is_active = Column(Boolean, default=True)
    email_confirmed = Column(Boolean, default=False)
    confirmation_token = Column(String(255), unique=True, nullable=True)
    reset_token = Column(String(255), unique=True, nullable=True)
    reset_token_expires = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    roles = relationship("UserRole", back_populates="user")
    startup_profile = relationship("StartupProfile", uselist=False, back_populates="user")
    enterprise_profile = relationship("EnterpriseProfile", uselist=False, back_populates="user")
    projects = relationship("Project", back_populates="startup")
    requests = relationship("Request", back_populates="enterprise")

class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)

class UserRole(Base):
    __tablename__ = "user_roles"
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    user = relationship("User", back_populates="roles")
    role = relationship("Role")

class StartupProfile(Base):
    __tablename__ = "startup_profiles"
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    team_name = Column(String(255), nullable=False)
    description = Column(Text)
    website = Column(String(255))
    founded_year = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    user = relationship("User", back_populates="startup_profile")

class EnterpriseProfile(Base):
    __tablename__ = "enterprise_profiles"
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    company_name = Column(String(255), nullable=False)
    industry = Column(String(100))
    description = Column(Text)
    website = Column(String(255))
    competencies = Column(ARRAY(Text), default=[])
    experience_years = Column(Integer)
    is_available = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    user = relationship("User", back_populates="enterprise_profile")

# ---------- Projects ----------
class Project(Base):
    __tablename__ = "projects"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    startup_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    title = Column(String(255), nullable=False)
    description = Column(Text)
    stage = Column(String(100))
    tags = Column(ARRAY(Text), default=[])
    status = Column(SAEnum(ProjectStatus), default=ProjectStatus.draft)
    overall_score = Column(Numeric(6,2), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    image_url = Column(Text, nullable=True)

    startup = relationship("User", back_populates="projects")
    reviews = relationship("ProjectReview", back_populates="project")

# ---------- Requests (заявки предприятий) ----------
class Request(Base):
    __tablename__ = "requests"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    title = Column(String(255), nullable=False)
    description = Column(Text)
    requirements = Column(Text)
    tags = Column(ARRAY(Text), default=[])
    status = Column(SAEnum(RequestStatus), default=RequestStatus.open)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    enterprise = relationship("User", back_populates="requests")
    responses = relationship("Response", back_populates="request")

# ---------- Review system (пока заготовка) ----------
class EvaluationCriteria(Base):
    __tablename__ = "evaluation_criteria"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    max_score = Column(Numeric(5,2), nullable=False)
    weight = Column(Numeric(5,4), default=1.0, nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

class ProjectReview(Base):
    __tablename__ = "project_reviews"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    expert_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))  # предприятие
    status = Column(SAEnum(ReviewStatus), default=ReviewStatus.assigned)
    review_token = Column(String(255), unique=True, nullable=True)           # <-- новый токен
    token_expires = Column(DateTime(timezone=True), nullable=True)           # <-- срок действия
    assigned_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at = Column(DateTime(timezone=True))
    final_comment = Column(Text)
    overall_score = Column(Numeric(6,2))

    __table_args__ = (UniqueConstraint("project_id", "expert_id"),)

    project = relationship("Project", back_populates="reviews")
    expert = relationship("User")
    scores = relationship("ReviewScore", back_populates="review")

class ReviewScore(Base):
    __tablename__ = "review_scores"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id = Column(UUID(as_uuid=True), ForeignKey("project_reviews.id", ondelete="CASCADE"))
    criterion_id = Column(Integer, ForeignKey("evaluation_criteria.id", ondelete="RESTRICT"))
    score = Column(Numeric(5,2), nullable=False)
    __table_args__ = (UniqueConstraint("review_id", "criterion_id"),)

    review = relationship("ProjectReview", back_populates="scores")
    criterion = relationship("EvaluationCriteria")

# ---------- Responses (отклики на проекты/заявки) ----------
class Response(Base):
    __tablename__ = "responses"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    request_id = Column(UUID(as_uuid=True), ForeignKey("requests.id", ondelete="CASCADE"), nullable=True)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Связи
    from_user = relationship("User")  
    request = relationship("Request", back_populates="responses")
    project = relationship("Project")  

    __table_args__ = (
        CheckConstraint(
            "(project_id IS NOT NULL AND request_id IS NULL) OR (project_id IS NULL AND request_id IS NOT NULL)",
            name="response_target_check"
        ),
    )