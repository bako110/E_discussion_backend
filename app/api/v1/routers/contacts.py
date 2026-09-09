"""Router contacts — repertoire E-discussion + synchro du carnet telephonique."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.user import ContactMatch, ContactSyncIn, UserPublic
from app.services import user_service

router = APIRouter()


@router.get("", response_model=list[UserPublic])
async def list_contacts(current_user: CurrentUser, db: DbSession):
    """Mes contacts E-discussion : comptes reconnus via la synchro du
    repertoire + personnes avec qui j'ai deja une conversation."""
    return await user_service.list_contacts(db, current_user)


@router.post("/sync", response_model=list[ContactMatch])
async def sync(body: ContactSyncIn, current_user: CurrentUser, db: DbSession):
    """Envoie les numeros du carnet d'adresses (E.164), retourne ceux qui
    correspondent a un compte E-discussion."""
    return await user_service.sync_contacts(db, current_user, body)
