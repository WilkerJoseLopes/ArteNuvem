import cloudconvert
import os
import tempfile

cloudconvert.configure(
    api_key=os.getenv("CLOUDCONVERT_API_KEY"),
    sandbox=False
)

def html_to_pdf(html_content: str) -> str:
    """
    Converte HTML em PDF usando CloudConvert
    Retorna a URL do PDF
    """

    # cria arquivo HTML temporário
    with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as f:
        f.write(html_content.encode("utf-8"))
        html_path = f.name

    job = cloudconvert.Job.create(payload={
        "tasks": {
            "import-file": {
                "operation": "import/upload"
            },
            "convert-pdf": {
                "operation": "convert",
                "input": "import-file",
                "output_format": "pdf",
                "engine": "chrome"
            },
            "export-file": {
                "operation": "export/url",
                "input": "convert-pdf"
            }
        }
    })

    upload_task = next(
        t for t in job["tasks"]
        if t["operation"] == "import/upload"
    )

    cloudconvert.Task.upload(
        task=upload_task,
        file_name=html_path
    )

    job = cloudconvert.Job.wait(job["id"])

    export_task = next(
        t for t in job["tasks"]
        if t["operation"] == "export/url"
    )

    return export_task["result"]["files"][0]["url"]

