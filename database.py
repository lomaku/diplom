from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session