import os
import cloudconvert
import requests
import shutil

cloudconvert.configure(
    api_key=os.getenv("CLOUDCONVERT_API_KEY"),
    sandbox=False # ou False se for live
)

def html_para_pdf(html_path: str, pdf_path: str):

    # 1️⃣ Criar job
    job = cloudconvert.Job.create({
        "tasks": {
            "import-html": {
                "operation": "import/upload"
            },
            "convert-pdf": {
                "operation": "convert",
                "input": "import-html",
                "output_format": "pdf",
                "engine": "chrome"
            },
            "export-pdf": {
                "operation": "export/url",
                "input": "convert-pdf"
            }
        }
    })

    # 2️⃣ Obter task de upload
    upload_task = next(
        t for t in job["tasks"]
        if t["operation"] == "import/upload"
    )

    # 3️⃣ Upload do ficheiro HTML
    cloudconvert.Task.upload(
        task=upload_task,
        file_name=html_path
    )

    # 🔴 4️⃣ AQUI entra o Job.wait (OBRIGATÓRIO)
    job = cloudconvert.Job.wait(job["id"])

    # 5️⃣ Obter task de export
    export_task = next(
        t for t in job["tasks"]
        if t["operation"] == "export/url"
    )

    # 6️⃣ Download do PDF
    pdf_url = export_task["result"]["files"][0]["url"]

    r = requests.get(pdf_url, stream=True)
    r.raise_for_status()

    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(r.raw, f)

