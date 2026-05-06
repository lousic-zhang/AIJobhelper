from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from app.models.application import (
    ApplicationCreateRequest,
    ApplicationListItem,
    ApplicationStatus,
    ApplicationStatusUpdateRequest,
)

try:
    from pymongo import ReturnDocument
except ImportError:  # pragma: no cover
    class ReturnDocument:
        AFTER = None


class ApplicationService:
    allowed_statuses: tuple[str, ...] = (
        "applied",
        "written_test",
        "interview",
        "hr_interview",
        "offer",
        "rejected",
        "closed",
    )

    def __init__(self, database: Any) -> None:
        self.collection = database["applications"]

    def create_application(self, user_id: str, payload: ApplicationCreateRequest) -> ApplicationListItem:
        now = datetime.utcnow()
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
            "company": payload.company,
            "position": payload.position,
            "channel": payload.channel,
            "status": payload.status,
            "delivery_time": payload.delivery_time or now,
            "deadline": payload.deadline,
            "note": payload.note,
            "created_at": now,
            "updated_at": now,
        }
        result = self.collection.insert_one(document)
        created = self.collection.find_one({"_id": result.inserted_id})
        return self._to_model(created)

    def list_applications(
        self,
        user_id: str,
        company: str | None = None,
        status: ApplicationStatus | str | None = None,
    ) -> list[ApplicationListItem]:
        query: dict[str, object] = {"user_id": user_id}
        if company:
            query["company"] = {"$regex": company, "$options": "i"}
        if status:
            query["status"] = status
        docs = self.collection.find(query).sort("updated_at", -1)
        return [self._to_model(doc) for doc in docs]

    def update_status(
        self,
        application_id: str,
        user_id: str,
        payload: ApplicationStatusUpdateRequest,
    ) -> ApplicationListItem:
        result = self.collection.find_one_and_update(
            {"_id": application_id, "user_id": user_id},
            {
                "$set": {
                    "status": payload.status,
                    "updated_at": datetime.utcnow(),
                    "note": payload.note,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if result is None:
            raise ValueError("Application record not found.")
        return self._to_model(result)

    def update_status_by_company_position(
        self,
        user_id: str,
        company: str,
        position: str,
        status: str,
        note: str = "",
    ) -> ApplicationListItem:
        result = self.collection.find_one_and_update(
            {
                "user_id": user_id,
                "company": {"$regex": f"^{company}$", "$options": "i"},
                "position": {"$regex": f"^{position}$", "$options": "i"},
            },
            {
                "$set": {
                    "status": status,
                    "updated_at": datetime.utcnow(),
                    "note": note,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if result is None:
            raise ValueError("Application record not found.")
        return self._to_model(result)

    def _to_model(self, document: dict[str, Any]) -> ApplicationListItem:
        mapped = dict(document)
        mapped["_id"] = str(mapped["_id"])
        return ApplicationListItem.model_validate(mapped)
