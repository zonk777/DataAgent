from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from ..models import DatasetColumnUpdate, DatasetUpdate, MySQLImportRequest
from ..services.audit import log_action
from ..services.auth import current_admin
from ..services.datasets import (
    dataset_quality,
    delete_dataset,
    get_dataset,
    import_dataset,
    import_mysql_dataset,
    list_datasets,
    update_column_description,
    update_dataset,
)
from ..services.permissions import (
    accessible_dataset_ids,
    ensure_dataset_access,
    get_dataset_permissions,
    require_data_manager,
    set_dataset_permissions,
)


router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("")
def datasets(request: Request) -> list[dict]:
    actor = current_admin(request)
    return list_datasets(accessible_dataset_ids(actor))


@router.post("/upload", status_code=201)
async def upload_dataset(
    request: Request,
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    description: str = Form(default=""),
) -> dict:
    actor = require_data_manager(request)
    try:
        result = await import_dataset(file, name, description)
    except ValueError as exc:
        log_action("upload_dataset", "dataset", None, str(exc), status="failed", actor=actor)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if accessible_dataset_ids(actor) is not None:
        set_dataset_permissions(actor["id"], [*get_dataset_permissions(actor["id"]), result["id"]])
    log_action("upload_dataset", "dataset", result["id"], file.filename or result["name"], actor=actor)
    return result


@router.post("/mysql/import", status_code=201)
def mysql_import(payload: MySQLImportRequest, request: Request) -> dict:
    actor = require_data_manager(request)
    try:
        result = import_mysql_dataset(payload)
    except ValueError as exc:
        log_action("import_mysql", "dataset", payload.table, str(exc), status="failed", actor=actor)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if accessible_dataset_ids(actor) is not None:
        set_dataset_permissions(actor["id"], [*get_dataset_permissions(actor["id"]), result["id"]])
    log_action("import_mysql", "dataset", result["id"], f"{payload.database}.{payload.table}", actor=actor)
    return result


@router.get("/{dataset_id}")
def dataset(dataset_id: int, request: Request) -> dict:
    actor = current_admin(request)
    ensure_dataset_access(actor, dataset_id)
    try:
        return get_dataset(dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{dataset_id}")
def edit_dataset(dataset_id: int, payload: DatasetUpdate, request: Request) -> dict:
    actor = require_data_manager(request)
    ensure_dataset_access(actor, dataset_id)
    try:
        result = update_dataset(dataset_id, payload.name, payload.description)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    log_action("update_dataset", "dataset", dataset_id, payload.name, actor=actor)
    return result


@router.patch("/{dataset_id}/columns/{column_name}")
def edit_dataset_column(dataset_id: int, column_name: str, payload: DatasetColumnUpdate, request: Request) -> dict:
    actor = require_data_manager(request)
    ensure_dataset_access(actor, dataset_id)
    try:
        result = update_column_description(dataset_id, column_name, payload.description)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    log_action("update_column", "dataset_column", f"{dataset_id}:{column_name}", payload.description, actor=actor)
    return result


@router.get("/{dataset_id}/quality")
def quality(dataset_id: int, request: Request) -> dict:
    actor = current_admin(request)
    ensure_dataset_access(actor, dataset_id)
    try:
        return dataset_quality(dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{dataset_id}", status_code=204)
def remove_dataset(dataset_id: int, request: Request) -> None:
    actor = require_data_manager(request)
    ensure_dataset_access(actor, dataset_id)
    try:
        delete_dataset(dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    log_action("delete_dataset", "dataset", dataset_id, "删除数据源", actor=actor)
