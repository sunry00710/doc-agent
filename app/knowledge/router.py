from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.documents.router import get_storage
from app.documents.storage import FileStorage
from app.identity.models import User
from app.identity.router import get_current_user
from app.knowledge.embeddings import FastEmbedProvider
from app.knowledge.schemas import SearchHit, SearchQuery
from app.knowledge.search import search

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
_embedding_provider = FastEmbedProvider()


@router.post("/search", response_model=list[SearchHit])
def search_knowledge(
    query: SearchQuery,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    storage: Annotated[FileStorage, Depends(get_storage)],
) -> list[SearchHit]:
    return search(session, storage, query, current_user, embedding_provider=_embedding_provider)
