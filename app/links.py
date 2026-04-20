from typing import Any

from beanie import Document
from beanie.odm.fields import Link
from bson import DBRef


def linked_document_id(value: Link[Any] | Document | Any) -> str:
    if isinstance(value, Link):
        return str(value.ref.id)
    return str(value.id)


def linked_document_ref(collection: str, document_id: Any) -> DBRef:
    return DBRef(collection, document_id)
