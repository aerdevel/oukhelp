import logging
import shutil
from pathlib import Path

from services.documents_store import delete_user_package_data, get_any_package
from services.registration_store import delete_user_registration_data, get_any_registration

FILES_ROOT = Path("data/files")


async def build_user_data_export(tg_user_id: int) -> dict:
    registration = await get_any_registration(tg_user_id)
    package = await get_any_package(tg_user_id)
    package_status = package[0] if package else None
    package_data = package[1] if package else None
    return {
        "tg_user_id": tg_user_id,
        "registration": registration,
        "documents_package_status": package_status,
        "documents_package": package_data,
    }


async def delete_user_data(tg_user_id: int) -> dict[str, bool]:
    reg_deleted = await delete_user_registration_data(tg_user_id)
    docs_deleted = await delete_user_package_data(tg_user_id)
    files_path = FILES_ROOT / str(tg_user_id)
    files_deleted = False
    if files_path.exists():
        try:
            shutil.rmtree(files_path)
            files_deleted = True
        except OSError as err:
            logging.warning("Не удалось удалить файлы пользователя %s: %s", tg_user_id, err)
    return {
        "registration_deleted": reg_deleted,
        "documents_deleted": docs_deleted,
        "files_deleted": files_deleted,
    }
