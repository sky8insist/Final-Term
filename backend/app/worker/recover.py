"""Re-dispatch unfinished material tasks after a host worker restart."""

from app.db.supabase_client import get_supabase_client
from app.worker.tasks import generate_exam, process_material


def recover_unfinished_tasks() -> int:
    client = get_supabase_client()
    rows = (
        client.table("processing_tasks")
        .select("id,user_id,material_id,task_type,status,attempts")
        .in_("status", ["queued", "running"])
        .order("created_at")
        .execute()
        .data
    )
    for row in rows:
        if row["status"] == "running":
            client.table("processing_tasks").update({
                "status": "queued",
                "stage": "queued",
                "progress": 0,
                "attempts": max(int(row.get("attempts", 0)) - 1, 0),
                "error_code": "worker_restart_recovery",
                "error_message": None,
                "finished_at": None,
            }).eq("id", row["id"]).eq("user_id", row["user_id"]).execute()
            if row.get("material_id"):
                client.table("materials").update({
                    "status": "queued",
                    "error_message": None,
                }).eq("id", row["material_id"]).eq("user_id", row["user_id"]).execute()
        if row.get("task_type") == "exam_generation":
            generate_exam.delay(row["id"])
        else:
            process_material.delay(row["id"])
        print(f"Recovered unfinished {row.get('task_type', 'material_ingestion')} task {row['id']}")
    return len(rows)


if __name__ == "__main__":
    count = recover_unfinished_tasks()
    print(f"Recovered {count} unfinished material task(s).")
